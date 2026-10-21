"""Entrée WSGI portable : python -B production.py, jamais app.run en public."""

from dataclasses import dataclass
from contextlib import closing
import importlib
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import time


@dataclass(frozen=True)
class Settings:
    database_path: Path
    hostnames: tuple[str, ...]
    port: int

    @classmethod
    def from_environment(cls):
        if not os.environ.get("CALCULATEDX_SECRET_KEY", "").strip():
            raise ValueError("CALCULATEDX_SECRET_KEY est obligatoire.")
        raw_path = os.environ.get("CALCULATEDX_DB_PATH", "")
        path = Path(raw_path)
        if not raw_path or not path.is_absolute() or not path.is_file():
            raise ValueError("CALCULATEDX_DB_PATH doit désigner une base existante par chemin absolu.")
        # Empêche toute initialisation accidentelle de la base locale de développement.
        if path.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ValueError("Utilisez un stockage persistant hors du dépôt.")
        hosts = tuple(value.strip().lower() for value in
                      os.environ.get("CALCULATEDX_HOSTNAMES", "").split(","))
        if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
                   and ".." not in host for host in hosts):
            raise ValueError("CALCULATEDX_HOSTNAMES doit contenir des noms DNS exacts, sans port ni joker.")
        try:
            port = int(os.environ.get("CALCULATEDX_PORT", "8080"))
        except ValueError:
            raise ValueError("CALCULATEDX_PORT doit être un port TCP valide.") from None
        if not 1 <= port <= 65535:
            raise ValueError("CALCULATEDX_PORT doit être un port TCP valide.")
        return cls(path.resolve(), hosts, port)


def validate_database(path):
    """Contrôle en lecture seule ; aucune création ni migration implicite."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(calculs)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(calculs)")}
        if not {"id", "nombre1", "operation", "nombre2", "resultat",
                "date_creation", "visitor_id"} <= columns:
            raise ValueError("Base non préparée : schéma de production requis.")
        if "idx_calculs_visitor_id" not in indexes:
            raise ValueError("Base non préparée : index visitor_id requis.")


class AccessLog:
    """Journalise uniquement méthode normalisée, statut et durée, jamais la requête."""

    def __init__(self, application, logger=None):
        self.application = application
        self.logger = logger or logging.getLogger("calculatedx.http")

    def __call__(self, environ, start_response):
        started = time.monotonic()
        status_code = 500

        def capture_status(status, headers, exc_info=None):
            nonlocal status_code
            status_code = int(status.split(" ", 1)[0])
            return start_response(status, headers, exc_info)

        def response_body():
            nonlocal status_code
            result = None
            try:
                result = self.application(environ, capture_status)
                yield from result
            except Exception:
                status_code = 500
                raise
            finally:
                try:
                    if result is not None and hasattr(result, "close"):
                        result.close()
                finally:
                    method = environ.get("REQUEST_METHOD", "")
                    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
                        method = "OTHER"
                    self.logger.log(logging.ERROR if status_code >= 500 else logging.INFO,
                                    "http method=%s status=%d duration_ms=%.1f",
                                    method, status_code, (time.monotonic() - started) * 1000)

        return response_body()


def create_application(settings):
    validate_database(settings.database_path)
    import database
    database.DB_PATH = settings.database_path
    # L'initialisation existante est idempotente sur le schéma déjà vérifié.
    application = importlib.import_module("app").app
    application.config.update(DEBUG=False, TESTING=False, TRUSTED_HOSTS=list(settings.hostnames))
    return AccessLog(application)


def server_options(settings):
    return dict(host="127.0.0.1", port=settings.port, threads=4,
                connection_limit=100, channel_timeout=30, cleanup_interval=5,
                max_request_header_size=8192, max_request_body_size=32 * 1024,
                expose_tracebacks=False, trusted_proxy=None,
                clear_untrusted_proxy_headers=True, ident="CALCULATEDX")


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings.from_environment()
        application = create_application(settings)
    except (ValueError, OSError, sqlite3.Error):
        # Les diagnostics ne révèlent ni secret, ni chemin, ni données SQLite.
        logging.getLogger("calculatedx.startup").error(
            "Démarrage refusé : vérifiez environnement, base préparée et droits de service.")
        return 1
    from waitress import serve
    serve(application, **server_options(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

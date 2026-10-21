"""Configuration privée du profil WSGI PythonAnywhere Free ; aucun serveur lancé."""

import json
import logging
import os
from pathlib import Path
import stat
import sys

from production import Settings, create_application as create_wsgi_application
from rate_limit import PythonAnywhereRateLimiter


def load_private_environment(path):
    path = path.resolve()
    if path.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Le fichier de configuration doit être hors du dépôt.")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("La configuration privée doit être accessible au seul propriétaire (0600).")
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ValueError("Configuration privée illisible ou JSON invalide.") from None
    required = {"CALCULATEDX_SECRET_KEY", "CALCULATEDX_DB_PATH", "CALCULATEDX_HOSTNAMES"}
    if (not isinstance(values, dict) or set(values) != required
            or not all(isinstance(value, str) and value.strip() for value in values.values())):
        raise ValueError("La configuration doit définir exactement les trois variables obligatoires.")
    os.environ.update(values)


def create_application(config_file=None):
    if config_file is None:
        config_file = Path.home() / ".config" / "calculatedx" / "production.json"
    load_private_environment(config_file)
    settings = Settings.from_environment()
    if len(settings.hostnames) != 1 or not settings.hostnames[0].endswith(".pythonanywhere.com"):
        raise ValueError("Utilisez le domaine exact de l'application PythonAnywhere Free.")
    application = create_wsgi_application(settings)
    application.application.extensions["request_rate_limiter"] = PythonAnywhereRateLimiter()
    logger = logging.getLogger("calculatedx.http")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return application

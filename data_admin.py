"""Outils hors ligne sans écrasement : prepare, backup, verify, restore.

    python -B data_admin.py --help

Tous les chemins sont absolus et hors dépôt. calculatedx.db est toujours refusée.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import shutil
import tempfile
import time

import database
from production import validate_database


def private_path(value, *, existing=True):
    path = Path(value)
    if not path.is_absolute() or path.name.casefold() == "calculatedx.db":
        raise ValueError("Chemin absolu hors dépôt requis ; calculatedx.db est interdite.")
    path = path.resolve()
    if (path.name.casefold() == "calculatedx.db"
            or path.is_relative_to(Path(__file__).resolve().parent)):
        raise ValueError("Chemin protégé ou situé dans le dépôt.")
    if not path.parent.is_dir():
        raise ValueError("Le répertoire privé doit déjà exister.")
    if os.name == "posix" and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError("Le répertoire doit être privé (0700).")
    if existing:
        if not path.is_file():
            raise ValueError("Fichier source absent.")
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("Le fichier doit être privé (0600).")
    elif path.exists():
        raise FileExistsError("La destination existe déjà ; aucun écrasement autorisé.")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_integrity(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Échec du contrôle d'intégrité SQLite.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Échec du contrôle des relations SQLite.")


def describe(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        check_integrity(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(calculs)")}
        rows = connection.execute("SELECT COUNT(*) FROM calculs").fetchone()[0]
        legacy = rows if "visitor_id" not in columns else connection.execute(
            "SELECT COUNT(*) FROM calculs WHERE visitor_id IS NULL").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    return {"format": 1, "sha256": sha256(path), "bytes": path.stat().st_size,
            "rows": rows, "legacy_rows": legacy, "schema_version": version}


def verify(snapshot, manifest):
    snapshot = private_path(snapshot)
    manifest = private_path(manifest)
    try:
        expected = json.loads(manifest.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ValueError("Manifeste illisible.") from None
    # Vérifier le hash avant d'ouvrir le snapshot avec SQLite.
    if (not isinstance(expected, dict) or expected.get("format") != 1
            or expected.get("sha256") != sha256(snapshot)
            or expected.get("bytes") != snapshot.stat().st_size):
        raise ValueError("Snapshot incomplet ou empreinte non concordante.")
    actual = describe(snapshot)
    if any(expected.get(key) != actual[key] for key in actual):
        raise ValueError("Les métadonnées du snapshot ne concordent pas.")
    return actual


def _build(destination, *, source=None, migrate=False, timeout=30, expected=None):
    destination = private_path(destination, existing=False)
    manifest = private_path(str(destination) + ".manifest.json", existing=False)
    if source is not None:
        source = private_path(source)
    if timeout <= 0:
        raise ValueError("Délai de copie invalide.")
    # Le répertoire temporaire est privé, sur le même volume que la destination.
    with tempfile.TemporaryDirectory(prefix=".calculatedx-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "snapshot.sqlite3"
        fd = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        if expected is not None:
            # Restaurer les octets vérifiés, sans normalisation de l'en-tête SQLite.
            # Une modification de la source entre verify et la copie doit échouer.
            with source.open("rb") as origin, staged.open("wb") as target:
                shutil.copyfileobj(origin, target, length=1024 * 1024)
            if sha256(staged) != expected["sha256"] or staged.stat().st_size != expected["bytes"]:
                raise ValueError("Snapshot modifié pendant la restauration.")
        with closing(sqlite3.connect(staged.as_uri() + "?mode=rw", uri=True)) as target:
            if source is not None and expected is None:
                deadline = time.monotonic() + timeout
                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Délai de sauvegarde dépassé.")
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True,
                                             timeout=1)) as origin:
                    origin.backup(target, pages=128, progress=progress, sleep=0.05)
            if migrate:
                with target:
                    target.execute("BEGIN IMMEDIATE")
                    database.appliquer_schema(target)
            check_integrity(target)
        if migrate:
            validate_database(staged)
        metadata = describe(staged)
        if expected is not None and metadata != expected:
            raise ValueError("La restauration ne correspond pas au snapshot vérifié.")
        metadata["created_utc"] = datetime.now(timezone.utc).isoformat()
        staged_manifest = Path(temporary) / "manifest.json"
        fd = os.open(staged_manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        with staged.open("r+b") as stream:
            os.fsync(stream.fileno())
        # Publication sans remplacement, même en cas de création concurrente.
        # Sans support des liens durs, échouer plutôt que remplacer un fichier.
        os.link(staged, destination)
        os.link(staged_manifest, manifest)
        if os.name == "posix":
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return metadata


def backup(source, destination, *, timeout=30):
    return _build(destination, source=source, timeout=timeout)


def prepare(destination, *, source=None, workers_stopped=False):
    if not workers_stopped:
        raise ValueError("Arrêt des workers et consoles d'écriture à confirmer avant migration.")
    # Une migration travaille sur une copie neuve ; la source reste inchangée.
    return _build(destination, source=source, migrate=True)


def restore(snapshot, manifest, destination):
    metadata = verify(snapshot, manifest)
    if metadata["schema_version"] != database.SCHEMA_VERSION:
        raise ValueError("Préparer une copie migrée du snapshot avant restauration.")
    validate_database(private_path(snapshot))
    return _build(destination, source=snapshot, expected=metadata)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="Base neuve ou copie migrée avant les workers")
    preparation.add_argument("--source")
    preparation.add_argument("--destination", required=True)
    preparation.add_argument("--workers-stopped", action="store_true", required=True)
    saving = commands.add_parser("backup", help="Snapshot cohérent vers une nouvelle destination")
    saving.add_argument("--source", required=True)
    saving.add_argument("--destination", required=True)
    checking = commands.add_parser("verify", help="Empreinte, intégrité et métadonnées")
    checking.add_argument("--snapshot", required=True)
    checking.add_argument("--manifest", required=True)
    recovery = commands.add_parser("restore", help="Restauration vers un nouveau fichier, jamais en place")
    recovery.add_argument("--snapshot", required=True)
    recovery.add_argument("--manifest", required=True)
    recovery.add_argument("--destination", required=True)
    options = vars(parser.parse_args(argv))
    command = options.pop("command")
    try:
        result = {"prepare": prepare, "backup": backup, "verify": verify, "restore": restore}[command](**options)
    except (ValueError, OSError, sqlite3.Error):
        print(json.dumps({"state": "failed", "operation": command}))
        return 1
    print(json.dumps({"state": "ok", "operation": command, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

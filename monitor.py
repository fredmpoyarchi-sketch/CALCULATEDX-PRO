"""Sonde disque en lecture seule, à planifier par l'hébergeur (aucun secret requis)."""

import json
import os
from pathlib import Path
import shutil


def check_storage(path, min_free_bytes=1024 ** 3, min_free_fraction=0.10):
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Base persistante inaccessible.")
    usage = shutil.disk_usage(path.parent)
    if usage.total <= 0:
        raise ValueError("Capacité du volume inconnue.")
    healthy = usage.free >= min_free_bytes and usage.free / usage.total >= min_free_fraction
    return {"check": "sqlite_volume", "state": "ok" if healthy else "critical",
            "free_bytes": usage.free, "total_bytes": usage.total}


def main():
    try:
        result = check_storage(Path(os.environ.get("CALCULATEDX_DB_PATH", "")))
    except (OSError, ValueError):
        result = {"check": "sqlite_volume", "state": "unknown"}
    print(json.dumps(result))
    return 0 if result["state"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

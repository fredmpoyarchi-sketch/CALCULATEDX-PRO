import importlib
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database


class StatisticsApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="calculatedx-statistics-api-")
        self.addCleanup(temp.cleanup)
        self.connections = []

        def isolated_connection():
            connection = sqlite3.connect(Path(temp.name) / "test.db")
            connection.row_factory = sqlite3.Row
            self.connections.append(connection)
            return connection

        connection_patch = patch.object(database, "obtenir_connexion", isolated_connection)
        connection_patch.start()
        self.addCleanup(connection_patch.stop)
        self.addCleanup(lambda: [connection.close() for connection in self.connections])
        database.initialiser_base()
        with patch.dict(os.environ, {"CALCULATEDX_SECRET_KEY": secrets.token_hex(32)}):
            self.module = importlib.import_module("app")
        config_patch = patch.dict(self.module.app.config, TESTING=True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.client = self.module.app.test_client()

    def test_empty_database(self):
        response = self.client.get("/api/v1/statistiques")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.json, {"total": 0, "par_operation": [], "par_jour": []})

    def test_operations_and_dates(self):
        with database.obtenir_connexion() as connexion:
            connexion.executemany(
                """INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation)
                VALUES (2, ?, 1, 3, ?)""",
                [("+", "2026-10-20 10:00:00"), ("-", "2026-10-19 12:00:00"),
                 ("+", "2026-10-20 18:00:00")])
        response = self.client.get("/api/v1/statistiques")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            "total": 3,
            "par_operation": [{"operation": "+", "total": 2},
                              {"operation": "-", "total": 1}],
            "par_jour": [{"jour": "2026-10-19", "total": 1},
                         {"jour": "2026-10-20", "total": 2}]})

    def test_database_error_is_generic_and_logged(self):
        with patch.object(database, "obtenir_connexion", side_effect=sqlite3.OperationalError(
                "sensitive internal database path")):
            with self.assertLogs(self.module.app.logger, level="ERROR") as logs:
                response = self.client.get("/api/v1/statistiques")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.json, {"erreur": "Impossible de récupérer les statistiques."})
        self.assertNotIn("sensitive", response.get_data(as_text=True))
        self.assertTrue(any(record.exc_info for record in logs.records))


if __name__ == "__main__":
    unittest.main()

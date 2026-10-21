from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.visitor_id = "a" * 64
        temp = tempfile.TemporaryDirectory(prefix="calculatedx-statistics-")
        self.addCleanup(temp.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(temp.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        # Le schéma réel est créé exclusivement dans la base temporaire.
        with closing(database.obtenir_connexion()) as connexion:
            with patch.object(database, "obtenir_connexion", return_value=connexion):
                database.initialiser_base()

    def insert_calculs(self, rows):
        with closing(database.obtenir_connexion()) as connexion:
            with connexion:
                connexion.executemany(
                    """INSERT INTO calculs
                    (nombre1, operation, nombre2, resultat, date_creation, visitor_id)
                    VALUES (2, ?, 1, 3, ?, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')""", rows)

    def test_empty_database(self):
        self.assertEqual(database.obtenir_statistiques(self.visitor_id), {
            "total": 0, "par_operation": [], "par_jour": []})

    def test_multiple_operations(self):
        self.insert_calculs([(op, "2026-10-20 12:00:00")
                            for op in ("+", "+", "-", "*", "/")])
        stats = database.obtenir_statistiques(self.visitor_id)
        self.assertEqual(stats["total"], 5)
        self.assertEqual({row["operation"]: row["total"]
                          for row in stats["par_operation"]},
                         {"+": 2, "-": 1, "*": 1, "/": 1})

    def test_days_are_grouped_and_sorted(self):
        self.insert_calculs([
            ("+", "2026-10-20 00:00:00"), ("-", "2026-09-30 23:59:59"),
            ("*", "2026-10-20 23:59:59"), ("/", "2025-12-31 12:00:00")])
        stats = database.obtenir_statistiques(self.visitor_id)
        self.assertEqual(stats["par_jour"], [
            {"jour": "2025-12-31", "total": 1},
            {"jour": "2026-09-30", "total": 1},
            {"jour": "2026-10-20", "total": 2}])
        self.assertEqual(stats["total"], 4)
        for key in ("par_operation", "par_jour"):
            self.assertEqual(sum(row["total"] for row in stats[key]), stats["total"])
        self.assertEqual(json.loads(json.dumps(stats)), stats)
        with closing(database.obtenir_connexion()) as connexion:
            with patch.object(database, "obtenir_connexion", return_value=connexion):
                self.assertEqual(len(database.lire_historique(self.visitor_id)), 4)

    def test_connection_closed_after_success(self):
        connexion = database.obtenir_connexion()
        with patch.object(database, "obtenir_connexion", return_value=connexion):
            database.obtenir_statistiques(self.visitor_id)
        with self.assertRaises(sqlite3.ProgrammingError):
            connexion.execute("SELECT 1")

    def test_connection_closed_after_error(self):
        connexion = database.obtenir_connexion()
        connexion.execute("DROP TABLE calculs")
        with patch.object(database, "obtenir_connexion", return_value=connexion):
            with self.assertRaises(sqlite3.OperationalError):
                database.obtenir_statistiques(self.visitor_id)
        with self.assertRaises(sqlite3.ProgrammingError):
            connexion.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()

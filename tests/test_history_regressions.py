import sqlite3
import unittest
from unittest.mock import patch

import database
from models import Calculatrice
import test_statistics_api


class HistoryRegressions(unittest.TestCase):
    # Le helper remplace la connexion avant tout import de l'application.
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def create_calculation(self):
        database.enregistrer_calcul(
            2, "+", 3, 5, visitor_id=self.visitor_id)
        return database.lire_historique(self.visitor_id)[0]["id"]

    def csrf_headers(self):
        self.client.get("/calcul")
        with self.client.session_transaction() as session:
            return {"X-CSRF-Token": session["csrf_token"]}

    def test_read_empty(self):
        self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_calculation_is_visible_from_existing_and_new_instances(self):
        calculator = Calculatrice()
        observer = Calculatrice()
        self.assertEqual(calculator.additionner(2, 3, self.visitor_id), 5)
        rows = calculator.obtenir_historique(self.visitor_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resultat"], 5)
        self.assertEqual(observer.obtenir_historique(self.visitor_id), rows)
        self.assertEqual(Calculatrice().obtenir_historique(self.visitor_id), rows)

    def test_deleted_calculation_never_reappears(self):
        calculator = Calculatrice()
        calculator.additionner(
            2, 3, visitor_id=self.visitor_id)
        identifier = calculator.obtenir_historique(self.visitor_id)[0]["id"]
        response = self.client.post(f"/historique/supprimer/{identifier}",
                                    headers=self.csrf_headers())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(calculator.obtenir_historique(self.visitor_id), [])
        self.assertEqual(Calculatrice().obtenir_historique(self.visitor_id), [])
        calculator.multiplier(4, 5, visitor_id=self.visitor_id)
        rows = calculator.obtenir_historique(self.visitor_id)
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["id"], identifier)
        self.assertEqual(rows[0]["resultat"], 20)
        self.assertEqual(database.obtenir_statistiques(self.visitor_id)["total"], 1)

    def test_read_order_and_values(self):
        first = self.create_calculation()
        database.enregistrer_calcul(8, "-", 2, 6, visitor_id=self.visitor_id)
        rows = Calculatrice().obtenir_historique(self.visitor_id)
        self.assertEqual(len(rows), 2)
        self.assertGreater(rows[0]["id"], first)
        self.assertEqual(rows[0]["operation"], "-")
        self.assertEqual(rows[0]["resultat"], 6)
        self.assertIsInstance(rows[0]["date_creation"], str)

    def test_history_page(self):
        self.create_calculation()
        response = self.client.get("/historique")
        self.assertEqual(response.status_code, 200)
        self.assertIn('history-data-row', response.get_data(as_text=True))

    def test_delete_existing(self):
        identifier = self.create_calculation()
        response = self.client.post(f"/historique/supprimer/{identifier}",
                                    headers=self.csrf_headers())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/historique"))
        self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_delete_missing(self):
        identifier = self.create_calculation()
        response = self.client.post(f"/historique/supprimer/{identifier + 1}",
                                    headers=self.csrf_headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(database.lire_historique(self.visitor_id)), 1)

    def test_delete_requires_csrf(self):
        identifier = self.create_calculation()
        headers = self.csrf_headers()
        for supplied in ({}, {"X-CSRF-Token": "incorrect"}):
            with self.subTest(headers=supplied):
                response = self.client.post(f"/historique/supprimer/{identifier}", headers=supplied)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(len(database.lire_historique(self.visitor_id)), 1)
        self.assertTrue(headers["X-CSRF-Token"])

    def test_get_cannot_delete(self):
        identifier = self.create_calculation()
        self.assertEqual(self.client.get(f"/historique/supprimer/{identifier}").status_code, 405)
        self.assertEqual(len(database.lire_historique(self.visitor_id)), 1)

    def test_connections_closed_after_read_and_delete(self):
        for operation in (lambda: database.lire_historique(self.visitor_id), lambda: database.supprimer_calcul(999, self.visitor_id)):
            with self.subTest(operation=operation):
                connexion = database.obtenir_connexion()
                with patch.object(database, "obtenir_connexion", return_value=connexion):
                    operation()
                with self.assertRaises(sqlite3.ProgrammingError):
                    connexion.execute("SELECT 1")

    def test_connections_closed_after_sqlite_error(self):
        for operation in (lambda: database.lire_historique(self.visitor_id), lambda: database.supprimer_calcul(999, self.visitor_id)):
            with self.subTest(operation=operation):
                connexion = sqlite3.connect(":memory:")
                self.connections.append(connexion)
                with patch.object(database, "obtenir_connexion", return_value=connexion):
                    with self.assertRaises(sqlite3.OperationalError):
                        operation()
                with self.assertRaises(sqlite3.ProgrammingError):
                    connexion.execute("SELECT 1")

    def test_read_sqlite_error_is_handled(self):
        with patch.object(database, "obtenir_connexion",
                          side_effect=sqlite3.OperationalError("private-database-path")):
            response = self.client.get("/historique")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-database-path", response.get_data(as_text=True))

    def test_delete_sqlite_error_is_handled(self):
        identifier = self.create_calculation()
        headers = self.csrf_headers()
        with patch.object(database, "obtenir_connexion",
                          side_effect=sqlite3.OperationalError("private-database-path")):
            response = self.client.post(f"/historique/supprimer/{identifier}", headers=headers)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-database-path", response.get_data(as_text=True))
        self.assertEqual(len(database.lire_historique(self.visitor_id)), 1)


if __name__ == "__main__":
    unittest.main()

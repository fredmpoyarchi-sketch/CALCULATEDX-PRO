import importlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database


class SecurityRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="calculatedx-tests-")
        self.addCleanup(self.temp.cleanup)
        self.connections = []

        def isolated_connection():
            connection = sqlite3.connect(Path(self.temp.name) / "test.db")
            connection.row_factory = sqlite3.Row
            self.connections.append(connection)
            return connection

        self.connection_patch = patch.object(database, "obtenir_connexion", isolated_connection)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.addCleanup(lambda: [connection.close() for connection in self.connections])
        with patch.dict(os.environ, {"CALCULATEDX_SECRET_KEY": secrets.token_hex(32)}):
            self.module = importlib.import_module("app")
        from models import Calculatrice
        self.calculator_patch = patch.object(self.module, "calculatrice", Calculatrice())
        self.calculator_patch.start()
        self.addCleanup(self.calculator_patch.stop)
        self.config_patch = patch.dict(self.module.app.config, TESTING=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.client = self.module.app.test_client()
        self.client.get("/calcul")
        with self.client.session_transaction() as session:
            self.token = session["csrf_token"]
            self.visitor_id = session["visitor_id"]

    def test_unknown_or_missing_form_operation(self):
        for operation in ("inconnue", None):
            with self.subTest(operation=operation):
                data = dict(nombre1="2", nombre2="3", csrf_token=self.token)
                if operation is not None:
                    data["operation"] = operation
                response = self.client.post("/calcul", data=data)
                self.assertEqual(response.status_code, 400)
                self.assertIn("Opération non valide", response.get_data(as_text=True))
                self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_nonfinite_api_results(self):
        cases = [("addition", 1e308, 1e308), ("soustraction", -1e308, 1e308),
                 ("multiplication", 1e308, 2), ("division", 1e308, 1e-308)]
        for operation, first, second in cases:
            with self.subTest(operation=operation):
                response = self.client.post("/api/v1/calculer", json={
                    "nombre1": first, "nombre2": second, "operation": operation,
                }, headers={"X-CSRF-Token": self.token})
                self.assertEqual(response.status_code, 400)
                def reject_constant(value):
                    raise AssertionError("Non-finite JSON constant: " + value)
                body = json.loads(response.get_data(as_text=True), parse_constant=reject_constant)
                self.assertIsInstance(body["erreur"], str)
                self.assertNotIn("resultat", body)
                self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_model_rejects_all_nonfinite_results(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.module.calculatrice.additionner(value, 0, self.visitor_id)
                self.assertEqual(database.lire_historique(self.visitor_id), [])
                self.assertEqual(self.module.calculatrice.obtenir_historique(self.visitor_id), [])

    def test_nonfinite_form_result(self):
        response = self.client.post("/calcul", data=dict(
            nombre1="1e308", nombre2="1e308", operation="addition", csrf_token=self.token))
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre fini", response.get_data(as_text=True))
        self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_valid_api_and_form(self):
        for operation, expected in (("addition", 10), ("soustraction", 6),
                                    ("multiplication", 16), ("division", 4)):
            with self.subTest(operation=operation):
                response = self.client.post("/api/v1/calculer", json=dict(
                    nombre1=8, nombre2=2, operation=operation),
                    headers={"X-CSRF-Token": self.token})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["resultat"], expected)
        response = self.client.post("/calcul", data=dict(
            nombre1="2", nombre2="3", operation="addition", csrf_token=self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(database.lire_historique(self.visitor_id)), 5)

    def test_csrf_still_required(self):
        response = self.client.post("/api/v1/calculer", json=dict(
            nombre1=2, nombre2=3, operation="addition"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(database.lire_historique(self.visitor_id), [])


if __name__ == "__main__":
    unittest.main()

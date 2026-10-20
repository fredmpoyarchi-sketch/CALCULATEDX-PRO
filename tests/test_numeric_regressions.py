"""Scénarios de caractérisation conservés et adaptés au contrat binary64 V3."""

import unittest
from unittest.mock import patch

import database
import test_statistics_api


SQLITE_MIN = -(2 ** 63)
SQLITE_MAX = 2 ** 63 - 1


class NumericFixture:
    # Remplace toutes les connexions avant l'import Flask ; nettoyage en fin de test.
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def post_addition(self, first, second=0, propagate=False):
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        with patch.dict(self.module.app.config, PROPAGATE_EXCEPTIONS=propagate):
            # Les erreurs attendues restent vérifiables sans polluer la sortie de la suite.
            with patch.object(self.module.app.logger, 'error'):
                return self.client.post('/api/v1/calculer', json={
                    'nombre1': first, 'nombre2': second, 'operation': 'addition',
                }, headers={'X-CSRF-Token': token})


class NumericContractTests(NumericFixture, unittest.TestCase):
    """Anciennes reproductions : refus sans perte ou succès cohérent en REAL."""

    def test_precision_at_binary64_and_sqlite_boundaries(self):
        cases = [
            (2 ** 53 - 1, True), (2 ** 53, True), (2 ** 53 + 1, False),
            (2 ** 53 + 2, True), (-(2 ** 53 + 1), False),
            (SQLITE_MIN, True), (SQLITE_MIN + 1, False), (SQLITE_MAX, False),
        ]
        for value, exact in cases:
            with self.subTest(value=value):
                before = database.lire_historique()
                response = self.post_addition(value)
                self.assertEqual(response.status_code, 200 if exact else 400)
                if exact:
                    self.assertEqual(response.json['resultat'], value)
                    self.assertEqual(database.lire_historique()[0]['resultat'], value)
                else:
                    self.assertIsInstance(response.json['erreur'], str)
                    self.assertEqual(database.lire_historique(), before)

    def test_out_of_sqlite_integer_range_uses_real_or_rejects_loss(self):
        for value in (SQLITE_MIN - 1, SQLITE_MAX + 1, 10 ** 20, -(10 ** 20)):
            with self.subTest(value=value):
                before = database.lire_historique()
                response = self.post_addition(value, propagate=True)
                exact = float(value) == value
                self.assertEqual(response.status_code, 200 if exact else 400)
                if exact:
                    self.assertEqual(database.lire_historique()[0]['resultat'], response.json['resultat'])
                else:
                    self.assertEqual(database.lire_historique(), before)

    def test_previous_result_overflow_and_operand_cancellation(self):
        for first, second in ((SQLITE_MAX, 1), (SQLITE_MIN, -1),
                              (SQLITE_MAX + 1, -(SQLITE_MAX + 1))):
            with self.subTest(first=first, second=second):
                before = database.lire_historique()
                response = self.post_addition(first, second, propagate=True)
                if first == SQLITE_MAX:
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(database.lire_historique(), before)
                else:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['resultat'], float(first) + float(second))
                    self.assertEqual(database.lire_historique()[0]['resultat'], response.json['resultat'])

    def test_previous_overflow_http_response_is_now_json_success(self):
        response = self.post_addition(10 ** 20)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(response.json['resultat'], 10 ** 20)
        self.assertEqual(database.lire_historique()[0]['resultat'], response.json['resultat'])

    def test_wide_float_domain_and_rounded_fractions(self):
        for value in (1e308, -1e308, 5e-324, 0.1):
            with self.subTest(value=value):
                response = self.post_addition(value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['resultat'], database.lire_historique()[0]['resultat'])
        response = self.post_addition(0.1, 0.2)
        self.assertEqual(response.json['resultat'], 0.1 + 0.2)
        self.assertEqual(database.lire_historique()[0]['resultat'], response.json['resultat'])

    def test_html_integer_precision_and_large_floats(self):
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        for value, status in [('9007199254740993', 400), ('9007199254740993.0', 200),
                              ('9.007199254740993e15', 200), ('9007199254740994', 200),
                              ('100000000000000000000', 200), ('1e308', 200),
                              ('nan', 400), ('inf', 400)]:
            with self.subTest(value=value):
                before = database.lire_historique()
                response = self.client.post('/calcul', data=dict(
                    nombre1=value, nombre2='0', operation='addition', csrf_token=token))
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.mimetype, 'text/html')
                if status == 400:
                    self.assertEqual(database.lire_historique(), before)
                    self.assertIn('Erreur de calcul', response.get_data(as_text=True))
                else:
                    self.assertEqual(database.lire_historique()[0]['resultat'], float(value))

    def test_nonfinite_results_never_persist_in_either_interface(self):
        before = database.lire_historique()
        response = self.post_addition(1e308, 1e308)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('resultat', response.json)
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        response = self.client.post('/calcul', data=dict(
            nombre1='1e308', nombre2='1e308', operation='addition', csrf_token=token))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(database.lire_historique(), before)


class NumericDesiredBehaviorTests(NumericFixture, unittest.TestCase):
    """Attentes : succès cohérent OU refus JSON 400, sans choisir la future plage."""

    def assert_consistent_success_or_rejection(self, first, second=0):
        before = database.lire_historique()
        response = self.post_addition(first, second)
        self.assertIn(response.status_code, (200, 400),
                      'Une entrée numérique doit réussir ou être refusée explicitement, sans HTTP 500.')
        self.assertEqual(response.mimetype, 'application/json')
        after = database.lire_historique()
        if response.status_code == 400:
            self.assertIsInstance(response.json.get('erreur'), str)
            self.assertNotIn('resultat', response.json)
            self.assertEqual(after, before)
        else:
            self.assertEqual(len(after), len(before) + 1)
            self.assertEqual(after[0]['resultat'], response.json['resultat'],
                             'Le résultat annoncé et le résultat persisté doivent être identiques.')

    def test_desired_precision_consistency(self):
        for value in (2 ** 53 - 1, 2 ** 53, 2 ** 53 + 1, 2 ** 53 + 2,
                      -(2 ** 53 + 1), SQLITE_MIN, SQLITE_MIN + 1, SQLITE_MAX):
            with self.subTest(value=value):
                self.assert_consistent_success_or_rejection(value)

    def test_desired_controlled_sqlite_integer_overflow(self):
        cases = [(SQLITE_MIN - 1, 0), (SQLITE_MAX + 1, 0), (10 ** 20, 0),
                 (-(10 ** 20), 0), (SQLITE_MAX, 1), (SQLITE_MIN, -1),
                 (SQLITE_MAX + 1, -(SQLITE_MAX + 1))]
        for first, second in cases:
            with self.subTest(first=first, second=second):
                self.assert_consistent_success_or_rejection(first, second)


if __name__ == '__main__':
    unittest.main()

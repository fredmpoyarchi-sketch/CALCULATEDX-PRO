import sqlite3
import unittest
from unittest.mock import patch

import test_statistics_api


class StatisticsPageTests(unittest.TestCase):
    # Réutilise l'isolation SQLite et l'initialisation Flask des tests API.
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def test_empty_page(self):
        response = self.client.get("/statistiques")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for text in ('id="stats-total">0', 'id="stats-days">0',
                     'id="stats-favorite">Aucune', 'Aucun calcul enregistré'):
            self.assertIn(text, html)
        self.assertNotIn('<meter', html)
        self.assertIn('aria-current="page"', html)

    def test_indicators_and_charts(self):
        with database_connection(self) as connection:
            connection.executemany(
                """INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation, visitor_id)
                VALUES (2, ?, 1, 3, ?, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')""",
                [("+", "2026-10-20"), ("-", "2026-10-19"), ("+", "2026-10-20")])
        response = self.client.get("/statistiques")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for text in ('id="stats-total">3', 'id="stats-days">2',
                     'id="stats-favorite">Addition', 'Répartition des opérations',
                     'Évolution quotidienne', '66.7 %'):
            self.assertIn(text, html)
        self.assertLess(html.index('2026-10-19'), html.index('2026-10-20'))
        self.assertEqual(html.count('<meter'), 4)

    def test_operation_is_escaped(self):
        with database_connection(self) as connection:
            connection.execute("""INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, visitor_id) VALUES (1, ?, 1, 2, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')""",
                ('<script>alert(1)</script>',))
        html = self.client.get('/statistiques').get_data(as_text=True)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_database_error(self):
        with patch.object(self.module, 'obtenir_statistiques',
                          side_effect=sqlite3.OperationalError('private-path')):
            with self.assertLogs(self.module.app.logger, level='ERROR'):
                response = self.client.get('/statistiques')
        self.assertEqual(response.status_code, 500)
        self.assertIn('Statistiques indisponibles', response.get_data(as_text=True))
        self.assertNotIn('private-path', response.get_data(as_text=True))

    def test_navigation_and_existing_pages(self):
        for route in ('/', '/calcul', '/historique'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertIn('href="/statistiques"', response.get_data(as_text=True))


def database_connection(test):
    # Connexions temporaires suivies et fermées par le setUp partagé.
    import database
    return database.obtenir_connexion()


if __name__ == '__main__':
    unittest.main()

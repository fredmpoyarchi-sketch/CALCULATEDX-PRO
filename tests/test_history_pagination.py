import unittest
from unittest.mock import patch

import database
import test_statistics_api


class HistoryPaginationTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def insert_rows(self, count):
        with database.obtenir_connexion() as connection:
            connection.executemany("""INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation, visitor_id)
                VALUES (?, '+', 1, ?, '2026-10-20 12:00:00', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')""",
                [(value, value + 1) for value in range(count)])

    def test_boundary_counts(self):
        for count in (0, 1, 20, 21, 65):
            with self.subTest(count=count):
                with database.obtenir_connexion() as connection:
                    connection.execute('DELETE FROM calculs')
                self.insert_rows(count)
                result = database.lire_historique_pagine(self.visitor_id)
                self.assertEqual(result['total'], count)
                self.assertEqual(len(result['calculs']), min(count, 20))
                self.assertEqual(result['pages'], max(1, (count + 19) // 20))
                self.assertEqual(result['page'], 1)
                response = self.client.get('/historique')
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn(f"Page 1 sur {result['pages']}", html)
                self.assertEqual(html.count('class="history-data-row"'), min(count, 20))

    def test_order_and_disjoint_pages(self):
        self.insert_rows(65)
        pages = [database.lire_historique_pagine(self.visitor_id, page) for page in range(1, 5)]
        self.assertEqual([len(page['calculs']) for page in pages], [20, 20, 20, 5])
        identifiers = [row['id'] for page in pages for row in page['calculs']]
        self.assertEqual(identifiers, sorted(set(identifiers), reverse=True))
        self.assertEqual(len(identifiers), 65)

    def test_invalid_and_out_of_range_parameters(self):
        self.insert_rows(21)
        for value, expected in [(None, 1), ('abc', 1), ('1.5', 1), ('-3', 1),
                                ('0', 1), ('2', 2), ('999', 2), ('9' * 100, 2)]:
            with self.subTest(value=value):
                query = {} if value is None else {'page': value}
                response = self.client.get('/historique', query_string=query)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'Page {expected} sur 2', response.get_data(as_text=True))

    def test_navigation_and_filter_scope(self):
        self.insert_rows(21)
        first = self.client.get('/historique').get_data(as_text=True)
        last = self.client.get('/historique?page=2').get_data(as_text=True)
        self.assertIn('rel="next" href="/historique?page=2', first)
        self.assertNotIn('rel="prev"', first)
        self.assertIn('rel="prev" href="/historique?page=1', last)
        self.assertNotIn('rel="next"', last)
        self.assertIn('Recherche globale', first)

    def test_does_not_load_full_history(self):
        self.insert_rows(21)
        with patch.object(database, 'lire_historique', side_effect=AssertionError('Full history read')):
            self.assertEqual(self.client.get('/historique').status_code, 200)

    def test_last_page_after_deletion(self):
        self.insert_rows(21)
        identifier = database.lire_historique_pagine(self.visitor_id, 2)['calculs'][0]['id']
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        response = self.client.post(f'/historique/supprimer/{identifier}', headers={'X-CSRF-Token': token})
        self.assertEqual(response.status_code, 302)
        self.assertIn('Page 1 sur 1', self.client.get('/historique?page=2').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()

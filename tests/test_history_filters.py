import unittest
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

import database
import test_statistics_api


class HistoryFilterTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def populate(self):
        with database.obtenir_connexion() as connection:
            connection.executemany('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, visitor_id) VALUES (?, ?, ?, ?, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')''',
                [(123.5, '+', 2, 125.5)] * 25 + [(123.5, '-', 2, 121.5)] * 21
                + [(7, '*', 8, 56)])

    def test_global_search_and_combined_counts(self):
        self.populate()
        for search, operation, count in [('123.5', '', 46), ('1.235e2', '', 46),
                                          ('123.50', '+', 25), ('', '-', 21),
                                          ('56', '*', 1), ('8', '*', 1)]:
            with self.subTest(search=search, operation=operation):
                first = database.lire_historique_pagine(self.visitor_id, recherche=search, operation=operation)
                self.assertEqual(first['total'], count)
                ids = []
                for page in range(1, first['pages'] + 1):
                    result = database.lire_historique_pagine(self.visitor_id, page, recherche=search, operation=operation)
                    self.assertEqual(result['total'], count)
                    ids.extend(row['id'] for row in result['calculs'])
                self.assertEqual(len(ids), count)
                self.assertEqual(ids, sorted(set(ids), reverse=True))

    def test_literal_special_characters_and_no_results(self):
        self.populate()
        for search in ('%', '_', "' OR 1=1 --", '<script>', 'not-a-number'):
            with self.subTest(search=search):
                result = database.lire_historique_pagine(self.visitor_id, 999, recherche=search)
                self.assertEqual(result['total'], 0)
                self.assertEqual(result['calculs'], [])
                response = self.client.get('/historique', query_string={'recherche': search})
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('Aucun résultat trouvé', html)
                self.assertNotIn('<script>', html)
                self.assertIn('name="recherche"', html)

    def test_navigation_and_new_search_resets_page(self):
        self.populate()
        response = self.client.get('/historique', query_string={'recherche': '123.5', 'operation': '+', 'page': 2})
        html = response.get_data(as_text=True)
        self.assertIn('Page 2 sur 2', html)
        self.assertIn('recherche=123.5', html)
        self.assertIn('operation=%2B', html)
        self.assertIn('method="GET"', html)
        form = html.split('class="history-filters">', 1)[1].split('</form>', 1)[0]
        self.assertNotIn('name="page"', form)
        fresh = self.client.get('/historique?recherche=123.5&operation=%2B')
        self.assertIn('Page 1 sur 2', fresh.get_data(as_text=True))

    def test_invalid_operation_and_page(self):
        self.populate()
        self.assertEqual(self.client.get('/historique?operation=unknown').status_code, 400)
        for page in ('abc', '-1', '0'):
            response = self.client.get('/historique', query_string={'page': page, 'operation': '-'})
            self.assertIn('Page 1 sur 2', response.get_data(as_text=True))

    def test_delete_preserves_filter_and_clamps_page(self):
        self.populate()
        row = database.lire_historique_pagine(self.visitor_id, 2, operation='-')['calculs'][0]
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        response = self.client.post(f"/historique/supprimer/{row['id']}", data={
            'csrf_token': token, 'page': '2', 'operation': '-', 'recherche': '123.5'})
        params = parse_qs(urlsplit(response.headers['Location']).query)
        self.assertEqual(params['operation'], ['-'])
        self.assertEqual(params['recherche'], ['123.5'])
        self.assertIn('Page 1 sur 1', self.client.get(response.headers['Location']).get_data(as_text=True))
        self.assertEqual(database.lire_historique_pagine(self.visitor_id, operation='-')['total'], 20)

    def test_filter_connection_is_closed(self):
        connection = database.obtenir_connexion()
        with patch.object(database, 'obtenir_connexion', return_value=connection):
            database.lire_historique_pagine(self.visitor_id, recherche='1', operation='+')
        import sqlite3
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import database
import test_statistics_api


class HistoryDateTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def test_date_controls_present_on_empty_page(self):
        response = self.client.get('/historique')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        form = html.split('class="history-filters">', 1)[1].split('</form>', 1)[0]
        self.assertIn('type="date" name="date_debut" value=""', form)
        self.assertIn('type="date" name="date_fin" value=""', form)
        self.assertIn('name="tri"', form)
        self.assertIn('value="recent" selected', form)
        self.assertIn('value="ancien"', form)

    def test_controls_transmitted_and_retained_on_next_page(self):
        self.insert(['2026-10-20 12:00:00'] * 21)
        criteria = dict(recherche='123.5', operation='+', date_debut='2026-10-19',
                        date_fin='2026-10-21', tri='ancien')
        calculator = self.module.calculatrice
        with patch.object(calculator, 'obtenir_historique_pagine',
                          wraps=calculator.obtenir_historique_pagine) as read:
            response = self.client.get('/historique', query_string=dict(criteria, page='2'))
            read.assert_called_once_with('2', '123.5', '+', '2026-10-19', '2026-10-21', 'ancien')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        form = html.split('class="history-filters">', 1)[1].split('</form>', 1)[0]
        self.assertIn('name="date_debut" value="2026-10-19"', form)
        self.assertIn('name="date_fin" value="2026-10-21"', form)
        self.assertIn('value="ancien" selected', form)
        self.assertIn('Page 2 sur 2', html)
        self.assertNotIn('name="page"', form)

    def insert(self, dates, operation='+'):
        with database.obtenir_connexion() as connection:
            connection.executemany('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation)
                VALUES (123.5, ?, 1, 124.5, ?)''', [(operation, value) for value in dates])

    def test_inclusive_day_boundaries(self):
        self.insert(['2026-10-19 23:59:59', '2026-10-20 00:00:00',
                     '2026-10-20 23:59:59.999', '2026-10-21 00:00:00'])
        result = database.lire_historique_pagine(date_debut='2026-10-20', date_fin='2026-10-20')
        self.assertEqual(result['total'], 2)
        self.assertEqual([row['id'] for row in result['calculs']], [3, 2])
        self.assertEqual(database.lire_historique_pagine(date_debut='2026-10-20')['total'], 3)
        self.assertEqual(database.lire_historique_pagine(date_fin='2026-10-20')['total'], 3)

    def test_invalid_dates_order_and_injection(self):
        cases = [{'date_debut': value} for value in (
            '2026-02-30', '2026-2-01', '20/10/2026', '20261020',
            '2026-10-20T00:00:00', "2026-10-20' OR 1=1 --")]
        cases += [{'date_fin': 'invalid'}, {'date_debut': '2026-10-21', 'date_fin': '2026-10-20'},
                  {'tri': 'id DESC; DROP TABLE calculs'}, {'tri': ''}]
        for criteria in cases:
            with self.subTest(criteria=criteria):
                response = self.client.get('/historique', query_string=criteria)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('Traceback', response.get_data(as_text=True))
        self.assertEqual(database.lire_historique_pagine()['total'], 0)

    def test_chronological_sort_and_ties(self):
        self.insert(['2026-10-21 12:00:00', '2026-10-19 12:00:00',
                     '2026-10-20 12:00:00', '2026-10-20 12:00:00'])
        for tri, expected in [('recent', [1, 4, 3, 2]), ('ancien', [2, 3, 4, 1])]:
            with self.subTest(tri=tri):
                rows = database.lire_historique_pagine(tri=tri)['calculs']
                self.assertEqual([row['id'] for row in rows], expected)

    def test_combined_filters_pagination_and_form(self):
        self.insert(['2026-10-20 12:00:00'] * 25)
        self.insert(['2026-10-20 12:00:00'], '-')
        self.insert(['2026-10-19 12:00:00'])
        criteria = dict(recherche='123.50', operation='+', date_debut='2026-10-20',
                        date_fin='2026-10-20', tri='ancien')
        first = database.lire_historique_pagine(**criteria)
        last = database.lire_historique_pagine(2, **criteria)
        self.assertEqual(first['total'], 25)
        self.assertEqual(last['total'], 25)
        self.assertEqual(len(first['calculs']), 20)
        self.assertEqual(len(last['calculs']), 5)
        html = self.client.get('/historique', query_string=criteria).get_data(as_text=True)
        self.assertIn('date_debut=2026-10-20', html)
        self.assertIn('date_fin=2026-10-20', html)
        self.assertIn('tri=ancien', html)
        form = html.split('class="history-filters">', 1)[1].split('</form>', 1)[0]
        self.assertNotIn('name="page"', form)

    def test_delete_preserves_date_criteria(self):
        self.insert(['2026-10-20 12:00:00'] * 21)
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        criteria = dict(page='2', recherche='123.5', operation='+',
                        date_debut='2026-10-20', date_fin='2026-10-20', tri='ancien')
        response = self.client.post('/historique/supprimer/21', data=dict(criteria, csrf_token=token))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.headers['Location']).query)
        for key, value in criteria.items():
            self.assertEqual(query[key], [value])
        html = self.client.get(response.headers['Location']).get_data(as_text=True)
        self.assertIn('Page 1 sur 1', html)


if __name__ == '__main__':
    unittest.main()

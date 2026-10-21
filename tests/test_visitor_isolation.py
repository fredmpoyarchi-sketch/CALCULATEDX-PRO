from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import patch
import unittest

import database
import test_statistics_api


class VisitorIsolationTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def visitors(self):
        # Neither client receives a preconfigured identity or shares a cookie jar.
        clients = [self.module.app.test_client(), self.module.app.test_client()]
        identities, tokens = [], []
        for client in clients:
            self.assertEqual(client.get('/calcul').status_code, 200)
            with client.session_transaction() as session:
                identities.append(session['visitor_id'])
                tokens.append(session['csrf_token'])
        self.assertNotEqual(identities[0], identities[1])
        self.assertNotEqual(tokens[0], tokens[1])
        return clients, identities, tokens

    def test_full_history_pagination_filters_and_statistics(self):
        clients, owners, _ = self.visitors()
        with closing(database.obtenir_connexion()) as connection, connection:
            for owner, count in zip(owners, (25, 21)):
                connection.executemany('''INSERT INTO calculs
                    (nombre1, operation, nombre2, resultat, date_creation, visitor_id)
                    VALUES (123.5, '+', 1, 124.5, '2026-10-20 12:00:00', ?)''',
                    [(owner,)] * count)
            connection.execute('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, date_creation)
                VALUES (99999, '/', 1, 99999, '2000-01-01')''')
        criteria = dict(recherche='123.50', operation='+', date_debut='2026-10-20',
                        date_fin='2026-10-20', tri='ancien')
        ids = []
        for client, owner, count in zip(clients, owners, (25, 21)):
            rows = self.module.calculatrice.obtenir_historique(owner)
            self.assertEqual(len(rows), count)
            ids.append({row['id'] for row in rows})
            for filters in ({}, criteria):
                first = database.lire_historique_pagine(owner, **filters)
                last = database.lire_historique_pagine(owner, 2, **filters)
                self.assertEqual((first['total'], first['pages']), (count, 2))
                self.assertEqual(last['total'], count)
                self.assertEqual(len(first['calculs']), 20)
                self.assertEqual(len(last['calculs']), count - 20)
                self.assertEqual({r['id'] for r in first['calculs'] + last['calculs']}, ids[-1])
                for page, expected in ((1, 20), (2, count - 20)):
                    response = client.get('/historique', query_string=dict(filters, page=page))
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertEqual(html.count('class="history-data-row"'), expected)
                    self.assertNotIn('99999', html)
            empty = database.lire_historique_pagine(owner, recherche="' OR 1=1 --")
            self.assertEqual(empty['total'], 0)
            self.assertEqual(database.lire_historique_pagine(owner, operation='/')['total'], 0)
            expected = dict(total=count, par_operation=[dict(operation='+', total=count)],
                            par_jour=[dict(jour='2026-10-20', total=count)])
            response = client.get('/api/v1/statistiques')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, expected)
            self.assertEqual(database.obtenir_statistiques(owner), expected)
            html = client.get('/statistiques')
            self.assertEqual(html.status_code, 200)
            self.assertIn(f'id="stats-total">{count}', html.get_data(as_text=True))
            self.assertNotIn('2000-01-01', html.get_data(as_text=True))
        self.assertTrue(ids[0].isdisjoint(ids[1]))

    def test_all_html_and_api_operations_are_owned_by_session(self):
        clients, owners, tokens = self.visitors()
        operations = ('addition', 'soustraction', 'multiplication', 'division')
        for index, (client, token) in enumerate(zip(clients, tokens)):
            for route in ('/calcul', '/api/v1/calculer'):
                for operation in operations:
                    payload = dict(nombre1=8 + index, nombre2=2, operation=operation,
                                   visitor_id=owners[1 - index])
                    options = {'json': payload} if route.startswith('/api') else {'data': payload}
                    response = client.post(route, headers={'X-CSRF-Token': token}, **options)
                    self.assertEqual(response.status_code, 200)
            rows = database.lire_historique(owners[index])
            self.assertEqual(len(rows), 8)
            self.assertEqual({r['nombre1'] for r in rows}, {8 + index})
            self.assertEqual({r['operation'] for r in rows}, {'+', '-', '*', '/'})
        for client, owner in zip(clients, owners):
            self.assertEqual(client.get('/api/v1/statistiques').json['total'], 8)
            with client.session_transaction() as session:
                self.assertEqual(session['visitor_id'], owner)

    def test_legacy_only_database_is_empty_for_both_visitors(self):
        clients, owners, _ = self.visitors()
        with closing(database.obtenir_connexion()) as connection, connection:
            connection.execute('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat)
                VALUES (987654, '+', 1, 987655)''')
        for client, owner in zip(clients, owners):
            self.assertEqual(database.lire_historique(owner), [])
            self.assertEqual(database.lire_historique_pagine(owner)['total'], 0)
            self.assertEqual(client.get('/api/v1/statistiques').json,
                             dict(total=0, par_operation=[], par_jour=[]))
            html = client.get('/historique').get_data(as_text=True)
            self.assertNotIn('987654', html)
            self.assertNotIn('class="history-data-row"', html)
            self.assertIn('id="stats-total">0', client.get('/statistiques').get_data(as_text=True))

    def test_writes_require_an_explicit_nonempty_owner(self):
        for owner in (None, '', 123, False):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                database.enregistrer_calcul(2, '+', 3, 5, owner)
        with self.assertRaises(TypeError):
            database.enregistrer_calcul(2, '+', 3, 5)
        with closing(database.obtenir_connexion()) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM calculs').fetchone()[0], 0)

    def test_cross_delete_csrf_and_legacy_rows(self):
        clients, owners, tokens = self.visitors()
        for owner in owners:
            database.enregistrer_calcul(2, '+', 3, 5, owner)
        identifier = database.lire_historique(owners[0])[0]['id']
        route = f'/historique/supprimer/{identifier}'
        self.assertEqual(clients[0].get(route).status_code, 405)
        for supplied in ({}, {'X-CSRF-Token': tokens[1]}, {'X-CSRF-Token': 'invalid'}):
            self.assertEqual(clients[0].post(route, headers=supplied).status_code, 400)
        # A valid attacker CSRF token grants no rights over another visitor's row.
        self.assertEqual(clients[1].post(route, headers={'X-CSRF-Token': tokens[1]}).status_code, 404)
        self.assertEqual(len(database.lire_historique(owners[0])), 1)
        self.assertEqual(clients[1].post('/historique/supprimer/999999',
                                       headers={'X-CSRF-Token': tokens[1]}).status_code, 404)
        for client, token in zip(clients, tokens):
            for route_calc in ('/calcul', '/api/v1/calculer'):
                payload = dict(nombre1=2, nombre2=3, operation='addition')
                options = {'json': payload} if route_calc.startswith('/api') else {'data': payload}
                self.assertEqual(client.post(route_calc, **options).status_code, 400)
                self.assertEqual(client.post(route_calc, headers={'X-CSRF-Token': tokens[1] if token == tokens[0] else tokens[0]},
                                             **options).status_code, 400)
        with closing(database.obtenir_connexion()) as connection, connection:
            legacy_id = connection.execute('''INSERT INTO calculs
                (nombre1, operation, nombre2, resultat) VALUES (99999, '+', 1, 100000)''').lastrowid
        for client, owner, token in zip(clients, owners, tokens):
            self.assertEqual(client.post(f'/historique/supprimer/{legacy_id}',
                                        data={'csrf_token': token}).status_code, 404)
            self.assertEqual(len(database.lire_historique(owner)), 1)
            self.assertEqual(client.get('/api/v1/statistiques').json['total'], 1)
        self.assertEqual(clients[0].post(route, data={'csrf_token': tokens[0]}).status_code, 302)
        self.assertEqual(database.lire_historique(owners[0]), [])
        self.assertEqual(len(database.lire_historique(owners[1])), 1)
        with closing(database.obtenir_connexion()) as connection:
            self.assertEqual(tuple(connection.execute('SELECT resultat, visitor_id FROM calculs WHERE id = ?',
                                                      (legacy_id,)).fetchone()), (100000, None))

    def test_legacy_migration_is_idempotent_and_preserves_values(self):
        with closing(database.obtenir_connexion()) as connection:
            root = Path(connection.execute('PRAGMA database_list').fetchone()[2]).parent
        path = root / 'legacy.db'
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('''CREATE TABLE calculs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nombre1 REAL NOT NULL,
                operation TEXT NOT NULL, nombre2 REAL NOT NULL, resultat REAL NOT NULL,
                date_creation TEXT DEFAULT CURRENT_TIMESTAMP)''')
            connection.execute('''INSERT INTO calculs VALUES
                (42, 0.1, '+', 0.2, 0.30000000000000004, '2020-01-02 03:04:05')''')
            before = tuple(connection.execute('SELECT * FROM calculs').fetchone())
        def connect():
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            return connection
        with patch.object(database, 'obtenir_connexion', side_effect=connect):
            database.initialiser_base()
            database.enregistrer_calcul(2, '+', 3, 5, 'owner')
            database.initialiser_base()
            database.initialiser_base()
            with closing(connect()) as connection:
                legacy = tuple(connection.execute('SELECT * FROM calculs WHERE id=42').fetchone())
                self.assertEqual(legacy, (*before, None))
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM calculs').fetchone()[0], 2)
                self.assertEqual(sum(row[1] == 'visitor_id' for row in connection.execute('PRAGMA table_info(calculs)')), 1)
            self.assertEqual(len(database.lire_historique('owner')), 1)
            self.assertEqual(database.lire_historique('stranger'), [])
            self.assertFalse(database.supprimer_calcul(42, 'owner'))


if __name__ == '__main__':
    unittest.main()

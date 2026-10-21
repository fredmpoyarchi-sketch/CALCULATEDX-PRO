from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import database
import test_statistics_api


class TrackingConnection(sqlite3.Connection):
    fail = False
    rolled_back = False

    def execute(self, *args, **kwargs):
        result = super().execute(*args, **kwargs)
        if self.fail and args[0].lstrip().startswith(('INSERT', 'CREATE')):
            raise sqlite3.OperationalError('simulated-write-error')
        return result

    def __exit__(self, exc_type, exc_value, traceback):
        self.rolled_back = exc_type is not None
        return super().__exit__(exc_type, exc_value, traceback)


class SqliteWriteTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def test_write_commit_rollback_and_close(self):
        # Chaque scénario utilise un fichier neuf exclusivement dans le dossier temporaire.
        root = Path(database.obtenir_connexion().execute('PRAGMA database_list').fetchone()[2]).parent
        for initialize in (True, False):
            for fail in (False, True):
                with self.subTest(initialize=initialize, fail=fail):
                    path = root / f'write-{initialize}-{fail}.db'
                    connection = sqlite3.connect(path, factory=TrackingConnection)
                    self.connections.append(connection)
                    if not initialize:
                        connection.execute('CREATE TABLE calculs (nombre1, operation, nombre2, resultat, visitor_id)')
                        connection.commit()
                    connection.fail = fail
                    operation = database.initialiser_base if initialize else lambda: database.enregistrer_calcul(
                        2, '+', 3, 5, visitor_id=self.visitor_id)
                    with patch.object(database, 'obtenir_connexion', return_value=connection):
                        if fail:
                            with self.assertRaises(sqlite3.OperationalError):
                                operation()
                        else:
                            operation()
                    self.assertEqual(connection.rolled_back, fail)
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute('SELECT 1')
                    with closing(sqlite3.connect(path)) as observer:
                        if initialize:
                            count = observer.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='calculs'").fetchone()[0]
                        else:
                            count = observer.execute('SELECT COUNT(*) FROM calculs').fetchone()[0]
                        self.assertEqual(count, 0 if fail else 1)

    def test_write_errors_are_generic_and_logged(self):
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        for route in ('/calcul', '/api/v1/calculer'):
            with self.subTest(route=route):
                payload = dict(nombre1=2, operation='addition', nombre2=3)
                options = {'json': payload} if route.startswith('/api') else {'data': payload}
                with patch.object(database, 'obtenir_connexion', side_effect=sqlite3.OperationalError('private-path')):
                    with self.assertLogs(self.module.app.logger, level='ERROR') as logs:
                        response = self.client.post(route, headers={'X-CSRF-Token': token}, **options)
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('private-path', response.get_data(as_text=True))
                self.assertTrue(any(record.exc_info for record in logs.records))
                if route.startswith('/api'):
                    self.assertIsInstance(response.json['erreur'], str)
                self.assertEqual(database.lire_historique(self.visitor_id), [])


if __name__ == '__main__':
    unittest.main()

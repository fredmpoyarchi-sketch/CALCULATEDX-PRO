from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from waitress.adjustments import Adjustments
from waitress.proxy_headers import proxy_headers_middleware

import database
import production


class ProductionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='calculatedx-production-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'persistent.db'
        with patch.object(database, 'DB_PATH', self.path):
            database.initialiser_base()
            database.enregistrer_calcul(2, '+', 3, 5, 'owner')
        self.environment = dict(CALCULATEDX_SECRET_KEY='test-only-production-secret-for-isolated-tests',
                                CALCULATEDX_DB_PATH=str(self.path),
                                CALCULATEDX_HOSTNAMES='calculator.test')

    def test_environment_and_actual_waitress_options(self):
        with patch.dict(os.environ, self.environment, clear=True):
            settings = production.Settings.from_environment()
        self.assertEqual(settings.database_path, self.path.resolve())
        options = Adjustments(**production.server_options(settings))
        self.assertEqual(options.host, '127.0.0.1')
        self.assertEqual(options.port, 8080)
        self.assertEqual(options.threads, 4)
        self.assertEqual(options.connection_limit, 100)
        self.assertEqual(options.max_request_body_size, 32768)
        self.assertEqual(options.max_request_header_size, 8192)
        self.assertLessEqual(options.channel_timeout, 30)
        self.assertIsNone(options.trusted_proxy)
        self.assertTrue(options.clear_untrusted_proxy_headers)
        self.assertFalse(options.expose_tracebacks)

    def test_short_session_keys_are_rejected_before_database_access(self):
        for secret in ('x', 'short-test-secret', 'a' * 31):
            with self.subTest(length=len(secret)), patch.dict(
                    os.environ, dict(self.environment, CALCULATEDX_SECRET_KEY=secret), clear=True):
                with patch.object(production.sqlite3, 'connect') as connect:
                    with self.assertRaises(ValueError) as error:
                        production.Settings.from_environment()
                    self.assertNotIn(secret, str(error.exception))
                    connect.assert_not_called()

    def test_invalid_environment_fails_without_creating_database(self):
        missing = self.path.parent / 'missing.db'
        variants = [dict(CALCULATEDX_SECRET_KEY=''), dict(CALCULATEDX_DB_PATH=''),
                    dict(CALCULATEDX_DB_PATH='relative.db'),
                    dict(CALCULATEDX_DB_PATH=str(missing)),
                    dict(CALCULATEDX_DB_PATH=str(Path(production.__file__).resolve())),
                    dict(CALCULATEDX_HOSTNAMES=''), dict(CALCULATEDX_HOSTNAMES='*.test'),
                    dict(CALCULATEDX_HOSTNAMES='https://calculator.test'),
                    dict(CALCULATEDX_HOSTNAMES='calculator.test:8080'),
                    dict(CALCULATEDX_PORT='0'), dict(CALCULATEDX_PORT='65536'),
                    dict(CALCULATEDX_PORT='invalid')]
        for variant in variants:
            with self.subTest(variant=variant), patch.dict(
                    os.environ, dict(self.environment, **variant), clear=True):
                with self.assertRaises(ValueError):
                    production.Settings.from_environment()
        self.assertFalse(missing.exists())

    def test_database_validation_preserves_schema_and_rows(self):
        before = self.path.read_bytes()
        production.validate_database(self.path)
        production.validate_database(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        old = self.path.parent / 'old.db'
        with closing(sqlite3.connect(old)) as connection, connection:
            connection.execute('CREATE TABLE calculs (id INTEGER, resultat REAL)')
            connection.execute('INSERT INTO calculs VALUES (42, 123.5)')
        before = old.read_bytes()
        with self.assertRaises(ValueError):
            production.validate_database(old)
        self.assertEqual(old.read_bytes(), before)
        missing = self.path.parent / 'missing.db'
        with self.assertRaises(sqlite3.Error):
            production.validate_database(missing)
        self.assertFalse(missing.exists())

    def test_wsgi_startup_uses_persistent_database_and_rejects_foreign_host(self):
        # Processus isolé : l'import Flask utilise exclusivement la base temporaire.
        script = '''
import json, re
from pathlib import Path
from werkzeug.test import Client
from werkzeug.wrappers import Response
from production import Settings, create_application
from database import lire_historique
settings = Settings.from_environment()
before_startup = settings.database_path.read_bytes()
application = create_application(settings)
assert settings.database_path.read_bytes() == before_startup
client = Client(application, Response)
response = client.get('/calcul', base_url='https://calculator.test')
assert response.status_code == 200
assert 'Secure' in response.headers['Set-Cookie']
token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
assert client.get('/', base_url='https://evil.test').status_code == 400
assert client.post('/api/v1/calculer', base_url='https://calculator.test',
                   json=dict(nombre1=2, nombre2=3, operation='addition')).status_code == 400
response = client.post('/api/v1/calculer', base_url='https://calculator.test',
    headers={'X-CSRF-Token': token}, json=dict(nombre1=8, nombre2=2, operation='division'))
assert response.status_code == 200 and response.json == {'resultat': 4}
assert client.get('/api/v1/statistiques', base_url='https://calculator.test').json['total'] == 1
assert len(lire_historique('owner')) == 1
assert not application.application.debug and not application.application.testing
print(json.dumps({'persistent': str(settings.database_path), 'status': 'ok'}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(production.__file__).parent,
                                env=dict(os.environ, **self.environment),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['persistent'], str(self.path.resolve()))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM calculs').fetchone()[0], 2)

    def test_untrusted_forwarded_headers_cannot_change_origin_or_scheme(self):
        seen = {}
        def application(environ, start_response):
            seen.update(environ)
            start_response('200 OK', [])
            return [b'ok']
        wrapped = proxy_headers_middleware(application, trusted_proxy=None, clear_untrusted=True)
        body = wrapped({'REMOTE_ADDR': '127.0.0.1', 'wsgi.url_scheme': 'http',
                        'HTTP_HOST': 'calculator.test',
                        'HTTP_X_FORWARDED_FOR': '198.51.100.1',
                        'HTTP_X_FORWARDED_PROTO': 'https',
                        'HTTP_X_FORWARDED_HOST': 'evil.test',
                        'HTTP_FORWARDED': 'for=198.51.100.1;proto=https'}, lambda *args: None)
        self.assertEqual(b''.join(body), b'ok')
        self.assertEqual(seen['REMOTE_ADDR'], '127.0.0.1')
        self.assertEqual(seen['wsgi.url_scheme'], 'http')
        self.assertEqual(seen['HTTP_HOST'], 'calculator.test')
        self.assertNotIn('HTTP_X_FORWARDED_FOR', seen)
        self.assertNotIn('HTTP_FORWARDED', seen)

    def test_access_logs_exclude_sensitive_request_fields(self):
        marker = 'SECRET-MARKER'
        environ = dict(REQUEST_METHOD='POST', PATH_INFO='/' + marker, QUERY_STRING=marker,
                       HTTP_COOKIE=marker, HTTP_AUTHORIZATION=marker,
                       HTTP_X_CSRF_TOKEN=marker, REMOTE_ADDR=marker)
        def application(environ, start_response):
            start_response('500 Internal Server Error', [])
            return [marker.encode()]
        wrapped = production.AccessLog(application)
        with self.assertLogs('calculatedx.http', level='INFO') as logs:
            self.assertEqual(b''.join(wrapped(environ, lambda *args: None)), marker.encode())
        self.assertEqual(logs.records[0].levelno, logging.ERROR)
        self.assertIn('status=500', logs.output[0])
        self.assertNotIn(marker, '\n'.join(logs.output))

    def test_streaming_failure_is_logged_and_closed_without_exception_details(self):
        closed = []
        def application(environ, start_response):
            start_response('200 OK', [])
            def body():
                try:
                    yield b'partial'
                    raise RuntimeError('SECRET-MARKER')
                finally:
                    closed.append(True)
            return body()
        wrapped = production.AccessLog(application)
        with self.assertLogs('calculatedx.http', level='INFO') as logs:
            with self.assertRaises(RuntimeError):
                list(wrapped({'REQUEST_METHOD': 'SECRET-MARKER'}, lambda *args: None))
        self.assertEqual(closed, [True])
        self.assertIn('method=OTHER status=500', logs.output[0])
        self.assertNotIn('SECRET-MARKER', '\n'.join(logs.output))

    def test_startup_failure_does_not_log_configuration_values(self):
        with patch.dict(os.environ, self.environment, clear=True):
            with patch.object(production, 'create_application',
                              side_effect=sqlite3.OperationalError('SECRET-MARKER')):
                with self.assertLogs('calculatedx.startup', level='ERROR') as logs:
                    self.assertEqual(production.main(), 1)
        self.assertNotIn('SECRET-MARKER', '\n'.join(logs.output))
        self.assertNotIn(self.environment['CALCULATEDX_SECRET_KEY'], '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()

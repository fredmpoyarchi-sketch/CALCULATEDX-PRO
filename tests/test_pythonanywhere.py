from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import database
import pythonanywhere_config


class PythonAnywhereTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='calculatedx-pythonanywhere-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / 'private.sqlite3'
        self.config = self.home / '.config' / 'calculatedx' / 'production.json'
        self.config.parent.mkdir(parents=True)
        with patch.object(database, 'DB_PATH', self.path):
            database.initialiser_base()
            database.enregistrer_calcul(2, '+', 3, 5, 'other-owner')
        self.values = dict(CALCULATEDX_SECRET_KEY='test-only-persistent-secret-for-isolated-tests',
                           CALCULATEDX_DB_PATH=str(self.path),
                           CALCULATEDX_HOSTNAMES='testuser.pythonanywhere.com')
        self.write_config(self.values)

    def write_config(self, values):
        self.config.write_text(json.dumps(values), encoding='utf-8')
        self.config.chmod(0o600)

    def test_private_environment_is_loaded_before_flask_without_changing_data(self):
        before = self.path.read_bytes()
        with patch.dict(os.environ, {}, clear=True):
            pythonanywhere_config.load_private_environment(self.config)
            for name, value in self.values.items():
                self.assertEqual(os.environ[name], value)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_invalid_or_extra_variables_are_rejected(self):
        cases = [[], {}, dict(self.values, CALCULATEDX_SECRET_KEY=''),
                 dict(self.values, CALCULATEDX_DB_PATH=123),
                 dict(self.values, UNEXPECTED='ignored-is-not-acceptable')]
        for values in cases:
            with self.subTest(values=values):
                self.write_config(values)
                with self.assertRaises(ValueError):
                    pythonanywhere_config.load_private_environment(self.config)
        self.config.write_text('{invalid-json', encoding='utf-8')
        with self.assertRaises(ValueError) as error:
            pythonanywhere_config.load_private_environment(self.config)
        self.assertNotIn('invalid-json', str(error.exception))

    def test_repository_config_is_rejected_before_read(self):
        with self.assertRaises(ValueError):
            pythonanywhere_config.load_private_environment(Path(database.__file__))

    def test_group_readable_secret_file_is_rejected(self):
        self.config.chmod(0o640)
        # Exercer aussi la règle POSIX sur le poste Windows, sans changer os global.
        with patch.object(pythonanywhere_config, 'os', wraps=os) as platform:
            platform.name = 'posix'
            with self.assertRaises(ValueError):
                pythonanywhere_config.load_private_environment(self.config)

    def test_wrong_domain_is_rejected_without_importing_flask(self):
        self.write_config(dict(self.values, CALCULATEDX_HOSTNAMES='evil.test'))
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(pythonanywhere_config, 'create_wsgi_application') as factory:
                with self.assertRaises(ValueError):
                    pythonanywhere_config.create_application(self.config)
                factory.assert_not_called()

    def test_actual_wsgi_import_from_foreign_cwd_static_paths_and_reload(self):
        root = Path(database.__file__).resolve().parent
        script = '''
import json, runpy, sys
from pathlib import Path
from unittest.mock import patch
from werkzeug.test import Client
from werkzeug.wrappers import Response
root, home = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(root))
with patch('pathlib.Path.home', return_value=home), \\
     patch('socket.socket', side_effect=AssertionError('No network')), \\
     patch('flask.Flask.run', side_effect=AssertionError('No app.run')), \\
     patch('waitress.serve', side_effect=AssertionError('No standalone server')):
    before = (home / 'private.sqlite3').read_bytes()
    application = runpy.run_path(str(root / 'pythonanywhere_wsgi.py'))['application']
    assert (home / 'private.sqlite3').read_bytes() == before
    flask_app = application.application
    assert not flask_app.debug and not flask_app.testing
    assert flask_app.config['SESSION_COOKIE_SECURE']
    assert flask_app.config['SESSION_COOKIE_HTTPONLY']
    assert flask_app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    limiter = flask_app.extensions['request_rate_limiter']
    tick = [0.0]
    limiter.clock = lambda: tick[0]
    client = Client(application, Response)
    def get(route):
        tick[0] += 2
        return client.get(route, base_url='https://testuser.pythonanywhere.com',
                          headers={'X-Real-IP': '198.51.100.1'})
    response = get('/calcul')
    assert response.status_code == 200
    assert 'Secure' in response.headers['Set-Cookie']
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    for resource in ('css/style.css', 'js/historique.js'):
        with get('/static/' + resource) as response:
            assert response.status_code == 200
            assert response.data == (root / 'static' / resource).read_bytes()
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert get('/api/v1/statistiques').json['total'] == 0
    tick[0] += 2
    response = client.post('/api/v1/calculer', base_url='https://testuser.pythonanywhere.com',
        headers={'X-Real-IP': '198.51.100.1', 'X-CSRF-Token': token},
        json=dict(nombre1=8, nombre2=2, operation='division'))
    assert response.status_code == 200 and response.json == {'resultat': 4}
    assert get('/api/v1/statistiques').json['total'] == 1
    assert client.get('/', base_url='https://evil.test').status_code == 400
    cookie = client.get_cookie('session', domain='testuser.pythonanywhere.com')
    application2 = runpy.run_path(str(root / 'pythonanywhere_wsgi.py'))['application']
    client2 = Client(application2, Response)
    client2.set_cookie('session', cookie.value, domain='testuser.pythonanywhere.com')
    assert client2.get('/api/v1/statistiques', base_url='https://testuser.pythonanywhere.com').json['total'] == 1
    assert application2.application.config['SECRET_KEY'] == 'test-only-persistent-secret-for-isolated-tests'
    print(json.dumps({'status': 'ok'}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(root), str(self.home)],
                                cwd=self.home, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'status': 'ok'})
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM calculs').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()

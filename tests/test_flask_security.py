from html.parser import HTMLParser
from http.cookies import SimpleCookie
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import database
import test_statistics_api


class PageSecurityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_handlers = []
        self.scripts = []
        self.in_script = False
        self.inline_script = []

    def handle_starttag(self, tag, attrs):
        self.inline_handlers.extend(name for name, _ in attrs if name.startswith('on'))
        if tag == 'script':
            self.scripts.append(dict(attrs))
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script and data.strip():
            self.inline_script.append(data)


class FlaskSecurityTests(unittest.TestCase):
    # Les connexions sont remplacées avant l'import de l'application.
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def headers(self):
        self.client.get('/calcul', base_url='https://localhost')
        with self.client.session_transaction() as session:
            return {'X-CSRF-Token': session['csrf_token']}

    def assert_security_headers(self, response):
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        directives = dict(part.strip().split(' ', 1)
                          for part in response.headers['Content-Security-Policy'].split(';'))
        for name in ('default-src', 'script-src', 'style-src', 'form-action'):
            self.assertEqual(directives[name], "'self'")
        for name in ('object-src', 'base-uri', 'frame-ancestors'):
            self.assertEqual(directives[name], "'none'")
        self.assertNotIn('unsafe-inline', response.headers['Content-Security-Policy'])
        self.assertNotIn('unsafe-eval', response.headers['Content-Security-Policy'])
        self.assertNotIn('Strict-Transport-Security', response.headers)

    def test_production_defaults_and_explicit_testing_mode(self):
        # Une instance neuve permet de vérifier les valeurs hors du patch TESTING.
        with patch.dict(os.environ, CALCULATEDX_SECRET_KEY='isolated-test-key', FLASK_DEBUG='1'):
            production = runpy.run_path(str(Path(self.module.__file__)))['app']
        self.assertFalse(production.debug)
        self.assertFalse(production.testing)
        self.assertTrue(production.config['SESSION_COOKIE_SECURE'])
        self.assertTrue(production.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(production.config['SESSION_COOKIE_SAMESITE'], 'Lax')
        self.assertEqual(production.config['MAX_CONTENT_LENGTH'], 16 * 1024)
        self.assertTrue(self.module.app.testing)
        self.assertFalse(self.module.app.debug)

    def test_cookie_flags_and_stable_visitor_over_https(self):
        client = self.module.app.test_client()
        response = client.get('/calcul', base_url='https://localhost')
        cookies = SimpleCookie()
        cookies.load(response.headers['Set-Cookie'])
        cookie = cookies[self.module.app.config['SESSION_COOKIE_NAME']]
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(cookie['domain'], '')
        self.assertEqual(cookie['path'], '/')
        with client.session_transaction() as session:
            owner, token = session['visitor_id'], session['csrf_token']
        response = client.post('/api/v1/calculer', base_url='https://localhost',
                               headers={'X-CSRF-Token': token},
                               json=dict(nombre1=2, nombre2=3, operation='addition'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'resultat': 5})
        with client.session_transaction() as session:
            self.assertEqual(session['visitor_id'], owner)
        self.assertEqual(len(database.lire_historique(owner)), 1)

    def test_headers_on_pages_api_and_static_resources(self):
        for route in ('/', '/calcul', '/historique', '/statistiques',
                      '/api/v1/statistiques', '/static/css/style.css', '/static/js/historique.js'):
            with self.subTest(route=route):
                with self.client.get(route, base_url='https://localhost') as response:
                    self.assertEqual(response.status_code, 200)
                    self.assert_security_headers(response)

    def test_headers_on_errors_and_redirect(self):
        token_headers = self.headers()
        cases = [self.client.get('/absent'), self.client.get('/api/v1/calculer'),
                 self.client.post('/api/v1/calculer', json={}),
                 self.client.post('/calcul', data='x' * (16 * 1024 + 1))]
        self.assertEqual([r.status_code for r in cases], [404, 405, 400, 413])
        database.enregistrer_calcul(2, '+', 3, 5, self.visitor_id)
        identifier = database.lire_historique(self.visitor_id)[0]['id']
        redirect = self.client.post(f'/historique/supprimer/{identifier}', headers=token_headers)
        self.assertEqual(redirect.status_code, 302)
        for response in [*cases, redirect]:
            self.assert_security_headers(response)
        for route in ('/statistiques', '/api/v1/statistiques'):
            with self.subTest(route=route), patch.object(database, 'obtenir_connexion',
                    side_effect=sqlite3.OperationalError('private-path')):
                with self.assertLogs(self.module.app.logger, level='ERROR'):
                    response = self.client.get(route)
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('private-path', response.get_data(as_text=True))
                self.assert_security_headers(response)

    def test_templates_have_no_inline_javascript(self):
        database.enregistrer_calcul(2, '+', 3, 5, self.visitor_id)
        for route in ('/', '/calcul', '/historique', '/statistiques'):
            with self.subTest(route=route):
                parser = PageSecurityParser()
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                parser.feed(response.get_data(as_text=True))
                self.assertEqual(parser.inline_handlers, [])
                self.assertEqual(parser.inline_script, [])
                if route == '/historique':
                    self.assertEqual(len(parser.scripts), 1)
                    self.assertEqual(parser.scripts[0]['src'], '/static/js/historique.js')
                    self.assertIn('defer', parser.scripts[0])
                    self.assertIn('class="history-delete-form"', response.get_data(as_text=True))

    def test_json_size_boundary(self):
        headers = self.headers()
        body = json.dumps(dict(nombre1=2, nombre2=3, operation='addition')).encode()
        for length, status, count in ((16383, 200, 1), (16384, 200, 2), (16385, 413, 2)):
            with self.subTest(length=length):
                response = self.client.post('/api/v1/calculer', headers=headers,
                    data=body + b' ' * (length - len(body)), content_type='application/json')
                self.assertEqual(response.status_code, status)
                self.assert_security_headers(response)
                self.assertEqual(len(database.lire_historique(self.visitor_id)), count)
                if status == 200:
                    self.assertEqual(response.json, {'resultat': 5})
                else:
                    self.assertIsInstance(response.json['erreur'], str)

    def test_form_size_boundary(self):
        headers = self.headers()
        body = urlencode(dict(nombre1=2, nombre2=3, operation='addition', padding='')).encode()
        for length, status, count in ((16383, 200, 1), (16384, 200, 2), (16385, 413, 2)):
            with self.subTest(length=length):
                response = self.client.post('/calcul', headers=headers,
                    data=body + b'x' * (length - len(body)),
                    content_type='application/x-www-form-urlencoded')
                self.assertEqual(response.status_code, status)
                self.assertEqual(len(database.lire_historique(self.visitor_id)), count)

    def test_oversized_requests_are_rejected_before_csrf_and_sqlite(self):
        headers = self.headers()
        database.enregistrer_calcul(2, '+', 3, 5, self.visitor_id)
        identifier = database.lire_historique(self.visitor_id)[0]['id']
        before = database.lire_historique(self.visitor_id)
        for route in ('/calcul', '/api/v1/calculer', f'/historique/supprimer/{identifier}'):
            for supplied in ({}, headers):
                with self.subTest(route=route, csrf=bool(supplied)):
                    with patch.object(database, 'obtenir_connexion',
                                      side_effect=AssertionError('SQLite must not be accessed')):
                        response = self.client.post(route, headers=supplied, data=b'x' * 16385)
                    self.assertEqual(response.status_code, 413)
                    self.assertEqual(database.lire_historique(self.visitor_id), before)
                    self.assert_security_headers(response)

    def test_oversized_multipart_is_rejected_without_write(self):
        headers = self.headers()
        with patch.object(database, 'obtenir_connexion',
                          side_effect=AssertionError('SQLite must not be accessed')):
            response = self.client.post('/calcul', headers=headers, content_type='multipart/form-data',
                data=dict(nombre1='2', nombre2='3', operation='addition', padding='x' * 16385))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(database.lire_historique(self.visitor_id), [])

    def test_stream_without_content_length_is_bounded(self):
        headers = self.headers()
        # Simule un corps chunked décodé par un serveur WSGI conforme.
        body = json.dumps(dict(nombre1=2, nombre2=3, operation='addition')).encode()
        for length, count in ((16383, 1), (16384, 2)):
            with self.subTest(length=length):
                response = self.client.post('/api/v1/calculer', headers=headers,
                    content_type='application/json', environ_overrides={
                        'CONTENT_LENGTH': '', 'wsgi.input_terminated': True,
                        'wsgi.input': BytesIO(body + b' ' * (length - len(body)))})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {'resultat': 5})
                self.assertEqual(len(database.lire_historique(self.visitor_id)), count)
        with patch.object(database, 'obtenir_connexion',
                          side_effect=AssertionError('SQLite must not be accessed')):
            response = self.client.post('/api/v1/calculer', headers=headers,
                content_type='application/json', environ_overrides={
                    'CONTENT_LENGTH': '', 'wsgi.input_terminated': True,
                    'wsgi.input': BytesIO(body + b' ' * (16385 - len(body)))})
        self.assertEqual(response.status_code, 413)
        self.assertIsInstance(response.json['erreur'], str)
        self.assertEqual(len(database.lire_historique(self.visitor_id)), 2)

    def test_csrf_remains_required_in_production_mode(self):
        headers = self.headers()
        with patch.dict(self.module.app.config, TESTING=False):
            for route in ('/calcul', '/api/v1/calculer'):
                for supplied in ({}, {'X-CSRF-Token': 'invalid'}):
                    options = {'json': dict(nombre1=2, nombre2=3, operation='addition')}
                    if route == '/calcul':
                        options = {'data': options['json']}
                    response = self.client.post(route, headers=supplied, **options)
                    self.assertEqual(response.status_code, 400)
                    self.assert_security_headers(response)
            self.assertEqual(database.lire_historique(self.visitor_id), [])
            for route in ('/calcul', '/api/v1/calculer'):
                payload = dict(nombre1=8, nombre2=2, operation='division')
                options = {'json': payload} if route.startswith('/api') else {'data': payload}
                response = self.client.post(route, headers=headers, **options)
                self.assertEqual(response.status_code, 200)
        self.assertEqual([row['resultat'] for row in database.lire_historique(self.visitor_id)], [4, 4])


if __name__ == '__main__':
    unittest.main()

from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import database
from rate_limit import PythonAnywhereRateLimiter
import test_statistics_api


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0

    def limiter(self, **options):
        return PythonAnywhereRateLimiter(clock=lambda: self.now, **options)

    def test_origin_quota_retry_and_recovery(self):
        limiter = self.limiter(origin_rate=1, origin_burst=2)
        origin = {'HTTP_X_REAL_IP': '198.51.100.1'}
        self.assertEqual([limiter.retry_after(origin) for _ in range(3)], [0, 0, 1])
        self.now = 0.5
        self.assertEqual(limiter.retry_after(origin), 1)
        self.now = 1.0
        self.assertEqual(limiter.retry_after(origin), 0)
        self.assertEqual(limiter.retry_after(origin), 1)

    def test_global_quota_applies_to_distinct_origins(self):
        limiter = self.limiter(global_rate=1, global_burst=2)
        results = [limiter.retry_after({'HTTP_X_REAL_IP': f'198.51.100.{n}'}) for n in (1, 2, 3)]
        self.assertEqual(results, [0, 0, 1])
        self.now = 1.0
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '198.51.100.3'}), 0)

    def test_cookie_xff_and_forwarded_cannot_reset_origin_quota(self):
        limiter = self.limiter(origin_burst=1)
        for index, expected in ((1, 0), (2, 1), (3, 1)):
            request = {'HTTP_X_REAL_IP': '198.51.100.1',
                       'HTTP_COOKIE': f'session={index}',
                       'HTTP_X_FORWARDED_FOR': f'203.0.113.{index}',
                       'HTTP_FORWARDED': f'for=203.0.113.{index}',
                       'REMOTE_ADDR': f'192.0.2.{index}'}
            self.assertEqual(limiter.retry_after(request), expected)

    def test_invalid_or_missing_ip_shares_unknown_quota(self):
        limiter = self.limiter(origin_burst=1)
        self.assertEqual(limiter.retry_after({}), 0)
        for raw in ('invalid', '1.2.3.4, 5.6.7.8', '1.2.3.4:80', 'fe80::1%eth0', 'x' * 100):
            self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': raw}), 1)

    def test_ipv6_prefix_and_mapped_ipv4_normalization(self):
        limiter = self.limiter(origin_burst=1)
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '2001:db8::1'}), 0)
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '2001:db8::2'}), 1)
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '2001:db8:0:1::1'}), 0)
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '::ffff:198.51.100.1'}), 0)
        self.assertEqual(limiter.retry_after({'HTTP_X_REAL_IP': '198.51.100.1'}), 1)

    def test_bounded_state_does_not_evict_active_quotas(self):
        limiter = self.limiter(origin_burst=1, max_origins=2)
        origin = lambda n: {'HTTP_X_REAL_IP': f'198.51.100.{n}'}
        self.assertEqual(limiter.retry_after(origin(1)), 0)
        self.assertEqual(limiter.retry_after(origin(2)), 0)
        self.assertEqual(limiter.retry_after(origin(3)), 0)
        self.assertEqual(limiter.retry_after(origin(4)), 1)
        self.assertEqual(limiter.retry_after(origin(1)), 1)
        self.assertEqual(len(limiter.origins), 2)
        self.now = 2.0
        self.assertEqual(limiter.retry_after(origin(4)), 0)
        self.assertLessEqual(len(limiter.origins), 2)

    def test_atomic_concurrent_requests_cannot_exceed_burst(self):
        limiter = self.limiter(global_burst=3, origin_burst=3)
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: limiter.retry_after(
                {'HTTP_X_REAL_IP': '198.51.100.1'}), range(24)))
        self.assertEqual(results.count(0), 3)
        self.assertEqual(sum(result > 0 for result in results), 21)


class FlaskRateLimitTests(unittest.TestCase):
    setUp = test_statistics_api.StatisticsApiTests.setUp

    def test_429_has_security_headers_and_cannot_write_or_delete(self):
        self.client.get('/calcul')
        with self.client.session_transaction() as session:
            headers = {'X-CSRF-Token': session['csrf_token']}
        database.enregistrer_calcul(2, '+', 3, 5, self.visitor_id)
        before = database.lire_historique(self.visitor_id)
        limiter = PythonAnywhereRateLimiter(global_burst=1, origin_burst=1, clock=lambda: 0.0)
        with patch.dict(self.module.app.extensions, request_rate_limiter=limiter):
            self.assertEqual(self.client.get('/', headers={'X-Real-IP': '198.51.100.1'}).status_code, 200)
            for route in ('/calcul', '/api/v1/calculer', f"/historique/supprimer/{before[0]['id']}"):
                with self.subTest(route=route):
                    with patch.object(database, 'obtenir_connexion',
                                      side_effect=AssertionError('No SQLite access after quota exceeded')):
                        response = self.client.post(route, headers=headers,
                            json=dict(nombre1=2, nombre2=3, operation='addition'))
                    self.assertEqual(response.status_code, 429)
                    self.assertIsInstance(response.json['erreur'], str)
                    self.assertEqual(response.headers['Retry-After'], '1')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                    self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                    self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
                    self.assertNotIn('Strict-Transport-Security', response.headers)
            # Le plafond de corps reste prioritaire sur le quota et n'écrit pas.
            response = self.client.post('/api/v1/calculer', headers=headers, data=b'x' * 16385)
            self.assertEqual(response.status_code, 413)
        self.assertEqual(database.lire_historique(self.visitor_id), before)


if __name__ == '__main__':
    unittest.main()

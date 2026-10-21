"""Limites en mémoire pour le worker unique PythonAnywhere Free, sans données disque."""

from collections import OrderedDict
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from math import ceil
from threading import Lock
from time import monotonic


@dataclass
class Bucket:
    tokens: float
    updated: float


class PythonAnywhereRateLimiter:
    """Confiance X-Real-IP réservée au frontal WSGI géré par PythonAnywhere.

    Jamais instancié par app.py ou le profil Waitress générique. Un rechargement
    remet les quotas à zéro ; plusieurs workers exigeraient un stockage partagé.
    """

    def __init__(self, global_rate=20, global_burst=40, origin_rate=1,
                 origin_burst=10, max_origins=4096, clock=monotonic):
        if min(global_rate, global_burst, origin_rate, origin_burst, max_origins) <= 0:
            raise ValueError("Les limites doivent être positives.")
        self.global_rate, self.global_burst = global_rate, global_burst
        self.origin_rate, self.origin_burst = origin_rate, origin_burst
        self.max_origins, self.clock = max_origins, clock
        self.global_bucket = Bucket(global_burst, clock())
        self.overflow_bucket = Bucket(origin_burst, clock())
        self.origins = OrderedDict()
        self.lock = Lock()

    @staticmethod
    def origin(environ):
        # PythonAnywhere documente X-Real-IP comme renseigné par son load balancer.
        # Ignorer XFF, Forwarded, REMOTE_ADDR et le cookie de session.
        raw = environ.get("HTTP_X_REAL_IP", "")
        if len(raw) > 45 or "%" in raw:
            return "unknown"
        try:
            address = ip_address(raw)
        except ValueError:
            return "unknown"
        if address.version == 6:
            if address.ipv4_mapped:
                return str(address.ipv4_mapped)
            return str(ip_network(f"{address}/64", strict=False))
        return str(address)

    @staticmethod
    def refill(bucket, now, rate, capacity):
        bucket.tokens = min(capacity, bucket.tokens + max(0, now - bucket.updated) * rate)
        bucket.updated = now

    def retry_after(self, environ):
        key = self.origin(environ)
        with self.lock:
            now = self.clock()
            # N'expirer que les quotas ayant entièrement récupéré leurs jetons.
            expiry = self.origin_burst / self.origin_rate
            while self.origins and now - next(iter(self.origins.values())).updated >= expiry:
                self.origins.popitem(last=False)
            bucket = self.origins.get(key)
            if bucket is None:
                if len(self.origins) < self.max_origins:
                    bucket = self.origins[key] = Bucket(self.origin_burst, now)
                else:
                    # Ne pas évincer un quota actif : les nouvelles IP partagent ce quota.
                    bucket = self.overflow_bucket
            else:
                self.origins.move_to_end(key)
            self.refill(self.global_bucket, now, self.global_rate, self.global_burst)
            self.refill(bucket, now, self.origin_rate, self.origin_burst)
            wait = max((1 - self.global_bucket.tokens) / self.global_rate,
                       (1 - bucket.tokens) / self.origin_rate, 0)
            if wait > 0:
                return max(1, ceil(wait))
            self.global_bucket.tokens -= 1
            bucket.tokens -= 1
            return 0

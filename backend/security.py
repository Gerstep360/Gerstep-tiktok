import base64
from collections import OrderedDict
import hashlib
import hmac
import json
import secrets
import time
import threading
import unicodedata


def clean_text(value, maximum, *, minimum=1):
    if not isinstance(value, str): raise ValueError('El texto debe ser una cadena.')
    value = unicodedata.normalize('NFKC', value).strip()
    if not minimum <= len(value) <= maximum: raise ValueError(f'Usá entre {minimum} y {maximum} caracteres.')
    if any(unicodedata.category(c).startswith('C') and c not in '\n\t' for c in value):
        raise ValueError('El mensaje tiene caracteres de control.')
    return value


class Security:
    def __init__(self, config):
        self.config = config
        self.rates = OrderedDict()
        self.lock = threading.RLock()
        self.admin_boot = secrets.token_hex(16)
        self.revoked = OrderedDict()

    def digest(self, value):
        return hmac.new(self.config.secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()

    def valid_key(self, actual, expected):
        return isinstance(actual, str) and hmac.compare_digest(self.digest(actual), self.digest(expected))

    def issue(self, role, *, user_id=None, nickname='', lifetime=86400):
        payload = {'role': role, 'id': user_id or secrets.token_hex(16), 'nickname': nickname,
                   'expires': int(time.time()) + lifetime}
        if role == 'admin': payload['boot'] = self.admin_boot
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
        return body + '.' + self.digest(body)

    def read(self, token, role):
        try:
            body, signature = token.split('.')
            if not hmac.compare_digest(signature, self.digest(body)): return None
            payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
            if payload['expires'] < time.time() or payload['role'] != role: return None
            if role=='admin':
                with self.lock:
                    if payload.get('boot')!=self.admin_boot or payload['id'] in self.revoked: return None
            return payload
        except (ValueError, TypeError, KeyError): return None

    def revoke_admin(self, session):
        with self.lock:
            now=time.time()
            for key,expires in list(self.revoked.items()):
                if expires<now: self.revoked.pop(key)
            self.revoked[session['id']]=session.get('expires',now+28800)
            # If the bounded revocation list fills, expire all old admin sessions.
            if len(self.revoked)>256:
                self.admin_boot=secrets.token_hex(16)
                self.revoked.clear()

    def allow(self, key, *, limit=1, period=15):
        with self.lock:
            return self._allow(key, limit, period)

    def _allow(self, key, limit, period):
        now = time.monotonic()
        while self.rates and next(iter(self.rates.values()))[1] < now:
            self.rates.popitem(last=False)
        count, until = self.rates.pop(key, (0, now + period))
        if now >= until: count, until = 0, now + period
        self.rates[key] = (count + 1, until)
        while len(self.rates) > 10000: self.rates.popitem(last=False)
        return count < limit

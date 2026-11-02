"""Passwords, session tokens, TOTP (2FA), encryption at rest, rate limiting."""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time
from collections import deque

# --------------------------------------------------------------------------
# Passwords: scrypt (memory-hard, Python standard library)
# --------------------------------------------------------------------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
COMMON = {"password", "motdepasse", "azerty123", "azertyuiop", "123456789", "1234567890", "qwerty123",
          "safqa12345", "maroc2026", "marocain", "bonjour123", "password123", "000000000", "admin12345",
          "123456789a", "azerty1234", "soleil1234", "iloveyou1"}


def hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(),
                                      base64.b64encode(dk).decode())


def verify_password(pw, stored):
    try:
        _algo, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = None


def burn_time(pw):
    """Same cost as a real check, so unknown e-mails cannot be detected by timing."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("dummy-password-for-timing")
    verify_password(pw, _DUMMY)


def password_problem(pw, email=""):
    if not isinstance(pw, str) or len(pw) < 10:
        return "Le mot de passe doit contenir au moins 10 caractères."
    if len(pw) > 200:
        return "Mot de passe trop long."
    low = pw.lower()
    if low in COMMON or (email and low.startswith(email.split("@")[0].lower())):
        return "Ce mot de passe est trop facile à deviner."
    if pw.isdigit() or pw.isalpha():
        return "Mélangez lettres et chiffres (ou symboles)."
    return None


# --------------------------------------------------------------------------
# Tokens: random, stored only as SHA-256
# --------------------------------------------------------------------------

def new_token(nbytes=32):
    return secrets.token_urlsafe(nbytes)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_code(length=8):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def new_digits(length=6):
    return "".join(secrets.choice("0123456789") for _ in range(length))


# --------------------------------------------------------------------------
# TOTP (RFC 6238) - Google Authenticator, Microsoft Authenticator...
# --------------------------------------------------------------------------

def totp_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1000000
    return "%06d" % code


def totp_now(secret, at=None):
    return _hotp(secret, int((at or time.time()) // 30))


def totp_verify(secret, code, at=None, window=1):
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    step = int((at or time.time()) // 30)
    return any(hmac.compare_digest(_hotp(secret, step + w), code) for w in range(-window, window + 1))


def totp_uri(secret, email, issuer="Safqa"):
    from urllib.parse import quote
    return "otpauth://totp/%s:%s?secret=%s&issuer=%s" % (quote(issuer), quote(email), secret, quote(issuer))


# --------------------------------------------------------------------------
# Encryption at rest: AES-256-GCM, key derived from SAFQA_DATA_KEY
# --------------------------------------------------------------------------

class Vault:
    """Encrypts payloads bound to their location (org/table/row) so a
    ciphertext cannot be moved to another company or record."""

    PREFIX = "v1:"

    def __init__(self, secret):
        if not secret or len(secret) < 16:
            raise ValueError("SAFQA_DATA_KEY doit contenir au moins 16 caractères.")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aes = AESGCM(hashlib.sha256(("safqa-data|" + secret).encode()).digest())

    def seal(self, data: bytes, aad: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, data, aad.encode())

    def open(self, blob: bytes, aad: str) -> bytes:
        return self._aes.decrypt(blob[:12], blob[12:], aad.encode())

    def seal_text(self, text: str, aad: str) -> str:
        return self.PREFIX + base64.b64encode(self.seal(text.encode(), aad)).decode()

    def open_text(self, value: str, aad: str) -> str:
        if not value.startswith(self.PREFIX):
            raise ValueError("format inconnu")
        return self.open(base64.b64decode(value[len(self.PREFIX):]), aad).decode()


# --------------------------------------------------------------------------
# Rate limiting (per process; lockouts that matter are stored in the DB)
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, limit, per_seconds):
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > per_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50000:          # bound memory
                for k in list(self._hits)[:10000]:
                    self._hits.pop(k, None)
            return True

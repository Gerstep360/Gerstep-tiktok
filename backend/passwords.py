"""Password hashes are separate from the native program's API credential."""
import hashlib
import hmac
import secrets


def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Usá una contraseña de 12 a 256 caracteres.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()
    return f'pbkdf2_sha256$310000${salt}${digest}'


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 256: return False
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 310000 or len(salt) != 32 or len(expected) != 64: return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError): return False

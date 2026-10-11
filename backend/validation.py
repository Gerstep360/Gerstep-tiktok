"""URL allowlist with no desktop or audio imports."""
import re
from urllib.parse import parse_qs, urlparse


def youtube_id(value):
    try:
        parsed = urlparse(str(value).strip())
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443): return None
        parts, identifier = parsed.path.strip('/').split('/'), None
        if parsed.hostname == 'youtu.be' and len(parts) == 1: identifier = parts[0]
        elif parsed.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
            if parsed.path == '/watch': identifier = parse_qs(parsed.query).get('v', [''])[0]
            elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}: identifier = parts[1]
        return identifier if identifier and re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier) else None
    except ValueError: return None

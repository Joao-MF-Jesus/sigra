from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


_SECRET = re.compile(r"(?i)(password|passwd|token|api[_-]?key|secret)=([^&\s]+)")


def sanitize(value: object, limit: int = 500) -> str:
    text = str(value)
    text = _SECRET.sub(r"\1=***", text)
    try:
        parsed = urlsplit(text)
        if parsed.scheme and parsed.hostname and (parsed.username or parsed.password):
            host = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
            text = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        pass
    return text[:limit]


def sanitize_endpoint(value: str) -> str:
    """Preserva somente scheme/host/path ou o path relativo, nunca credenciais."""
    try:
        parsed = urlsplit(value)
        path = parsed.path or "/"
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
            return urlunsplit((parsed.scheme, host, path, "", ""))
        return path
    except ValueError:
        return "/redacted-endpoint"

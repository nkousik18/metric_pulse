"""
Request keys shared by the recorder and the replay shim (docs/hosting-scope.md §6.1-6.2).

A recorded response is looked up by a key built from the request the SPA makes. The same rules are
implemented in JavaScript in `demo/static/replay.js` (`requestKey`); `tests/test_demo_site.py`
runs both on the same inputs, so the two can't drift apart.

    GET  /api/metrics/?days=60                 ->  GET /api/metrics/?days=60
    GET  /api/anomalies/?threshold=2           ->  GET /api/anomalies/?threshold=2.0
    POST /api/investigate/ {"metric": "x", …}  ->  POST /api/investigate/?current_date="…"&metric="x"&…

Query values are kept as the raw strings from the URL, except `threshold`, normalized to one
decimal (the slider sends "2" for 2.0). POST body values are JSON-encoded, so `true` and `"true"`
stay different. Parameters are sorted by name.
"""

import json
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlsplit


def _normalize_query(path: str, name: str, value: str) -> str:
    if path == '/api/anomalies/' and name == 'threshold':
        return f'{float(value):.1f}'
    return value


def request_key(method: str, url: str, body: Optional[Dict] = None) -> str:
    """The lookup key for one request. `url` may carry a query string."""
    parts = urlsplit(url)
    path = parts.path
    params = {name: _normalize_query(path, name, value)
              for name, value in parse_qsl(parts.query, keep_blank_values=True)}
    for name, value in (body or {}).items():
        params[name] = json.dumps(value, separators=(',', ':'), ensure_ascii=False)
    query = '&'.join(f'{name}={params[name]}' for name in sorted(params))
    return f'{method.upper()} {path}' + (f'?{query}' if query else '')

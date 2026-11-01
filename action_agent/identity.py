"""
Deterministic identities (docs/action-agent-scope.md §5, D1).

Both hashes go through canonical JSON (sorted keys, no whitespace), so the
same logical input always hashes the same regardless of dict ordering, and a
JSON array of fields can't collide the way naive string concatenation can
("ab"+"c" == "a"+"bc").
"""

import hashlib
import json
from typing import Any

# dataset_id used for the built-in Olist/Redshift pipeline (onboarded datasets
# use their own onboarding dataset_id).
OLIST_DATASET_ID = 'olist'


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def anomaly_id(dataset_id: str, metric: str, anomaly_date: str) -> str:
    """D1: segment is deliberately not part of an anomaly's identity."""
    return _sha256([dataset_id, metric, anomaly_date])


def idempotency_key(anomaly_id_: str, action_type: str, params: dict) -> str:
    """An edited action has new params and therefore a new key, by design (D8)."""
    return _sha256([anomaly_id_, action_type, params])

"""
Schema-fingerprint cache mechanism (docs/scoping.md Section 7.5). A confirmed
classification is only reusable across runs if the source schema hasn't
changed since it was confirmed -- this is the fingerprint that decides that.
"""

import hashlib
from typing import Dict

from onboarding.profiling import ColumnProfile


def schema_fingerprint(profiles: Dict[str, ColumnProfile]) -> str:
    """
    SHA-256 of sorted (name, dtype) pairs -- order-independent (insertion order
    of the profiles dict doesn't matter), changes on any rename/retype/add/remove.
    """
    pairs = sorted((p.name, p.dtype) for p in profiles.values())
    return hashlib.sha256(str(pairs).encode()).hexdigest()

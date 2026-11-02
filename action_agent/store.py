"""
actions.db -- the Action Agent's durable record (docs/action-agent-scope.md D5, D11).

Two rules hold by construction:
- `action_log` is append-only. SQLite triggers raise on UPDATE and DELETE, so
  a status change, an approval, an expiry or an execution is always a new row.
- `proposals` is insert-only too. A proposal's content never changes after
  it is written (an approver's edit is a new `edited` log row carrying the new
  params), and its status is derived from its latest log event. UNIQUE
  (anomaly_id) enforces D1's one-proposal-per-anomaly rule at the database
  level, not just in application code.

The idempotency guarantee (§5) is also enforced in SQL: a partial unique index
allows at most one `executed` row per idempotency key.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

# Events that end a proposal's lifecycle.
TERMINAL_EVENTS = frozenset({
    'policy_rejected', 'rejected', 'expired', 'executed', 'execution_failed',
    'execution_blocked', 'duplicate_skipped',
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id     TEXT PRIMARY KEY,
    anomaly_id      TEXT NOT NULL UNIQUE,
    dataset_id      TEXT NOT NULL,
    metric          TEXT NOT NULL,
    anomaly_date    TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    proposal_json   TEXT NOT NULL,
    evidence_json   TEXT NOT NULL,
    narrative       TEXT NOT NULL,
    proposer        TEXT NOT NULL,
    thread_id       TEXT NOT NULL,
    trace_id        TEXT,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id      TEXT NOT NULL REFERENCES proposals(proposal_id),
    event            TEXT NOT NULL,
    actor            TEXT NOT NULL,
    action_type      TEXT,
    params_json      TEXT,
    idempotency_key  TEXT,
    policy_json      TEXT,
    payload_json     TEXT,
    external_id      TEXT,
    detail           TEXT,
    trace_id         TEXT,
    created_at       TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_execution_per_key
    ON action_log(idempotency_key) WHERE event = 'executed';

CREATE TRIGGER IF NOT EXISTS action_log_no_update
    BEFORE UPDATE ON action_log
    BEGIN SELECT RAISE(ABORT, 'action_log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS action_log_no_delete
    BEFORE DELETE ON action_log
    BEGIN SELECT RAISE(ABORT, 'action_log is append-only'); END;

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id       TEXT NOT NULL,
    category         TEXT NOT NULL,
    cause            TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppressions (
    suppression_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id       TEXT NOT NULL,
    reason           TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls (
    control_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       TEXT NOT NULL,
    metric           TEXT NOT NULL,
    dimension        TEXT NOT NULL,
    segment          TEXT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('above', 'below')),
    threshold        REAL NOT NULL,
    owner            TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL
);
"""


class DuplicateAnomalyError(Exception):
    """D1: this anomaly already has a proposal, in any status."""


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _dumps(value) -> Optional[str]:
    return None if value is None else json.dumps(value, sort_keys=True, default=str)


class ActionStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute('PRAGMA foreign_keys = ON')
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # --- proposals ---

    def find_by_anomaly(self, anomaly_id: str) -> Optional[Dict]:
        row = self._conn.execute('SELECT * FROM proposals WHERE anomaly_id = ?', (anomaly_id,)).fetchone()
        return self._proposal_dict(row) if row else None

    def get_proposal(self, proposal_id: str) -> Optional[Dict]:
        row = self._conn.execute('SELECT * FROM proposals WHERE proposal_id = ?', (proposal_id,)).fetchone()
        return self._proposal_dict(row) if row else None

    def create_proposal(
        self, *, proposal_id: str, anomaly_id: str, dataset_id: str, metric: str, anomaly_date: str,
        proposal: Dict, evidence: Dict, narrative: str, proposer: str,
        trace_id: Optional[str], created_at: datetime, expires_at: datetime,
    ) -> str:
        """proposal_id doubles as the LangGraph checkpointer thread_id."""
        try:
            with self._tx() as c:
                c.execute(
                    'INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (proposal_id, anomaly_id, dataset_id, metric, anomaly_date,
                     proposal['action_type'], _dumps(proposal['params']), _dumps(proposal),
                     _dumps(evidence), narrative, proposer, proposal_id, trace_id,
                     _now_iso(created_at), _now_iso(expires_at)),
                )
        except sqlite3.IntegrityError as e:
            if 'anomaly_id' in str(e):
                raise DuplicateAnomalyError(anomaly_id) from e
            raise
        return proposal_id

    def _proposal_dict(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        for key in ('params', 'proposal', 'evidence'):
            d[key] = json.loads(d.pop(f'{key}_json'))
        return d

    # --- action log ---

    def log(
        self, proposal_id: str, event: str, actor: str, *, action_type: Optional[str] = None,
        params: Optional[Dict] = None, idempotency_key: Optional[str] = None,
        policy: Optional[Dict] = None, payload: Optional[Dict] = None,
        external_id: Optional[str] = None, detail: Optional[str] = None,
        trace_id: Optional[str] = None, now: Optional[datetime] = None,
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                'INSERT INTO action_log (proposal_id, event, actor, action_type, params_json, '
                'idempotency_key, policy_json, payload_json, external_id, detail, trace_id, created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (proposal_id, event, actor, action_type, _dumps(params), idempotency_key,
                 _dumps(policy), _dumps(payload), external_id, detail, trace_id, _now_iso(now)),
            )
            return cur.lastrowid

    def events(self, proposal_id: Optional[str] = None) -> List[Dict]:
        if proposal_id:
            rows = self._conn.execute(
                'SELECT * FROM action_log WHERE proposal_id = ? ORDER BY log_id', (proposal_id,))
        else:
            rows = self._conn.execute('SELECT * FROM action_log ORDER BY log_id')
        out = []
        for row in rows:
            d = dict(row)
            for key in ('params', 'policy', 'payload'):
                raw = d.pop(f'{key}_json')
                d[key] = json.loads(raw) if raw else None
            out.append(d)
        return out

    def status(self, proposal_id: str) -> str:
        """Latest terminal event, else 'pending'."""
        for event in reversed(self.events(proposal_id)):
            if event['event'] in TERMINAL_EVENTS:
                return event['event']
        return 'pending'

    def has_approval(self, proposal_id: str, idempotency_key: str) -> bool:
        """F1: an approval row (approve, or an approver's own edit) for exactly this key."""
        row = self._conn.execute(
            "SELECT 1 FROM action_log WHERE proposal_id = ? AND idempotency_key = ? "
            "AND event IN ('approved', 'edited') LIMIT 1", (proposal_id, idempotency_key)).fetchone()
        return row is not None

    def execution_for_key(self, idempotency_key: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT log_id, external_id FROM action_log WHERE idempotency_key = ? AND event = 'executed'",
            (idempotency_key,)).fetchone()
        return dict(row) if row else None

    def pending_proposals(self) -> List[Dict]:
        rows = self._conn.execute('SELECT proposal_id FROM proposals ORDER BY created_at').fetchall()
        return [self.get_proposal(r['proposal_id']) for r in rows if self.status(r['proposal_id']) == 'pending']

    # --- local effect tables (written by the local executors) ---

    def insert_effect(self, table: str, row: Dict, now: Optional[datetime] = None) -> int:
        if table not in ('annotations', 'suppressions', 'controls'):
            raise ValueError(f'unknown effect table: {table}')
        row = {**row, 'created_at': _now_iso(now)}
        cols = ', '.join(row)
        marks = ', '.join('?' for _ in row)
        with self._tx() as c:
            return c.execute(f'INSERT INTO {table} ({cols}) VALUES ({marks})', tuple(row.values())).lastrowid

    def effects(self, table: str) -> List[Dict]:
        if table not in ('annotations', 'suppressions', 'controls'):
            raise ValueError(f'unknown effect table: {table}')
        return [dict(r) for r in self._conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]

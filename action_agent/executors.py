"""
Executors: the only code that has an effect (docs/action-agent-scope.md §5, §9).

Each executor takes a dry run (build_dry_run's output, which is exactly what the approver saw)
and performs it. Idempotency and F1 approval checks happen in the graph's `execute` node before
an executor is ever called. Executors don't decide anything.

As of A4:
- annotate_anomaly / suppress_alerts / create_control write their local effect tables in
  actions.db; local pipeline runs read them (action_agent/hooks.py: D3 suppression, D4 controls).
- notify_owner goes through alerting.notifier (NotifierExecutor). With the default
  ALERT_CHANNEL=outbox it is a local Markdown file and always runs. A channel that leaves the
  machine (the archived sns) runs only with `live=True`; otherwise it is simulated.
- open_incident opens a GitHub Issue (GitHubIssueExecutor), only with `live=True` (the CLI's
  `--live`) and a configured repo and token; otherwise it is simulated.

"Live" means: allowed to cause effects outside this machine (§9's risk mitigation).
"""

from typing import Dict, List, Optional, Protocol

from action_agent.store import ActionStore
from config import settings


class Executor(Protocol):
    def execute(self, dry_run: Dict) -> Dict:
        """Returns {'outcome': str, 'external_id': str | None}. Raises on failure."""
        ...


class LocalStoreExecutor:
    def __init__(self, store: ActionStore):
        self.store = store

    def execute(self, dry_run: Dict) -> Dict:
        action_type, payload, key = dry_run['action_type'], dry_run['payload'], dry_run['idempotency_key']
        if action_type == 'annotate_anomaly':
            table = 'annotations'
            row = {'anomaly_id': payload['anomaly_id'], 'category': payload['category'],
                   'cause': payload['cause']}
        elif action_type == 'suppress_alerts':
            table = 'suppressions'
            row = {'anomaly_id': payload['anomaly_id'], 'reason': payload['reason'],
                   'expires_at': payload['expires_at']}
        elif action_type == 'create_control':
            table = 'controls'
            row = {k: payload[k] for k in ('dataset_id', 'metric', 'dimension', 'segment',
                                           'direction', 'threshold', 'owner', 'expires_at')}
        else:
            raise ValueError(f'LocalStoreExecutor cannot run {action_type}')
        rowid = self.store.insert_effect(table, {**row, 'idempotency_key': key})
        return {'outcome': 'applied', 'external_id': f'{table}:{rowid}'}


def owner_recipient(owner: Dict) -> str:
    name, email = owner.get('name'), owner.get('email')
    if name and email:
        return f'{name} <{email}>'
    return email or name or owner.get('id') or 'unknown'


class NotifierExecutor:
    """notify_owner through alerting.notifier: a message to the owner resolved from owners.yaml
    (never an LLM param). The idempotency key goes in the message metadata."""

    def __init__(self, live: bool = False, channel: Optional[str] = None, outbox_dir=None):
        self.live, self.channel, self.outbox_dir = live, channel, outbox_dir

    def execute(self, dry_run: Dict) -> Dict:
        from alerting.notifier import resolve_channel, send_alert

        channel = resolve_channel(self.channel)
        if channel != 'outbox' and not self.live:
            return {'outcome': 'simulated', 'external_id': None}
        owner, payload = dry_run['target']['owner'], dry_run['payload']
        result = send_alert(
            payload['subject'], payload['body'], recipient=owner_recipient(owner), channel=channel,
            outbox_dir=self.outbox_dir,
            metadata={'action': 'notify_owner', 'owner_id': owner.get('id'),
                      'anomaly_id': dry_run['anomaly_id'], 'idempotency_key': dry_run['idempotency_key']})
        if result.get('status') != 'sent':
            raise RuntimeError(f"notifier did not send ({channel}): {result}")
        return {'outcome': 'sent', 'external_id': f"{channel}:{result.get('message_id')}"}


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    """The three GitHub REST calls open_incident needs. Uses `requests`; base_url is injectable so
    tests can point it at a local HTTP server."""

    LABEL = 'metricpulse'

    def __init__(self, repo: str, token: str, api_url: str = 'https://api.github.com', timeout: float = 15):
        if not repo or '/' not in repo:
            raise ValueError(f"GitHub repo must be 'owner/name', got {repo!r}")
        if not token:
            raise ValueError('GitHub token is not set (GITHUB_TOKEN)')
        self.repo, self.api_url, self.timeout = repo, api_url.rstrip('/'), timeout
        self._headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                         'X-GitHub-Api-Version': '2022-11-28'}

    @classmethod
    def from_settings(cls) -> 'GitHubClient':
        return cls(settings.ACTION_GITHUB_REPO, settings.GITHUB_TOKEN, settings.GITHUB_API_URL)

    def _request(self, method: str, path: str, **kwargs):
        import requests

        response = requests.request(method, f'{self.api_url}{path}', headers=self._headers,
                                    timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            raise GitHubError(f'GitHub {method} {path} -> {response.status_code}: {response.text[:300]}')
        return response.json()

    def find_issue_with(self, marker: str, max_pages: int = 5) -> Optional[Dict]:
        """An existing MetricPulse issue (any state) whose body carries this marker. Uses the
        list endpoint, not search, because search is eventually consistent."""
        for page in range(1, max_pages + 1):
            issues = self._request('GET', f'/repos/{self.repo}/issues',
                                   params={'labels': self.LABEL, 'state': 'all', 'per_page': 100, 'page': page})
            for issue in issues:
                if 'pull_request' not in issue and marker in (issue.get('body') or ''):
                    return issue
            if len(issues) < 100:
                return None
        return None

    def create_issue(self, title: str, body: str, labels: List[str]) -> Dict:
        return self._request('POST', f'/repos/{self.repo}/issues',
                             json={'title': title, 'body': body, 'labels': labels})

    def close_issue(self, number: int, comment: Optional[str] = None) -> Dict:
        if comment:
            self._request('POST', f'/repos/{self.repo}/issues/{number}/comments', json={'body': comment})
        return self._request('PATCH', f'/repos/{self.repo}/issues/{number}',
                             json={'state': 'closed', 'state_reason': 'not_planned'})


def issue_marker(idempotency_key: str) -> str:
    return f'<!-- metricpulse:idempotency_key={idempotency_key} -->'


def issue_number(external_id: str) -> int:
    """The issue number from an issue URL (what open_incident stores as external_id)."""
    return int(str(external_id).rstrip('/').rsplit('/', 1)[-1])


class GitHubIssueExecutor:
    """open_incident. The idempotency key is written into the issue body as an HTML comment, and an
    issue already carrying it is reused. So even a crash between GitHub's reply and the
    `executed` log row can't open a second issue on a re-run."""

    def __init__(self, live: bool = False, client: Optional[GitHubClient] = None):
        self.live, self._client = live, client

    def client(self) -> GitHubClient:
        if self._client is None:
            self._client = GitHubClient.from_settings()
        return self._client

    def execute(self, dry_run: Dict) -> Dict:
        if not self.live:
            return {'outcome': 'simulated', 'external_id': None}
        client, payload = self.client(), dry_run['payload']
        marker = issue_marker(dry_run['idempotency_key'])
        existing = client.find_issue_with(marker)
        if existing:
            return {'outcome': 'already_open', 'external_id': existing['html_url']}
        labels = list(dict.fromkeys([GitHubClient.LABEL, *payload.get('labels', [])]))
        issue = client.create_issue(payload['title'], f"{payload['body']}\n\n{marker}", labels)
        return {'outcome': 'opened', 'external_id': issue['html_url']}

    def undo(self, external_id: Optional[str], reason: str) -> Dict:
        if not external_id or not str(external_id).startswith('http'):
            return {'outcome': 'nothing_to_close'}          # it was simulated
        if not self.live:
            raise RuntimeError('closing a real GitHub issue needs --live')
        self.client().close_issue(issue_number(external_id), comment=f'Undone in MetricPulse: {reason}')
        return {'outcome': 'closed'}


class SimulatedExecutor:
    """Sends nothing. Kept for callers that want an executor with no effect at all."""

    def execute(self, dry_run: Dict) -> Dict:
        return {'outcome': 'simulated', 'external_id': None}


class RecordingExecutor:
    """Test double from §9's risk table: records each call and has no side effects."""

    def __init__(self):
        self.calls: List[Dict] = []

    def execute(self, dry_run: Dict) -> Dict:
        self.calls.append(dry_run)
        return {'outcome': 'recorded', 'external_id': f"recorded:{len(self.calls)}"}


def default_executors(store: ActionStore, live: bool = False,
                      github_client: Optional[GitHubClient] = None, outbox_dir=None) -> Dict[str, Executor]:
    local = LocalStoreExecutor(store)
    return {
        'annotate_anomaly': local,
        'suppress_alerts': local,
        'create_control': local,
        'notify_owner': NotifierExecutor(live=live, outbox_dir=outbox_dir),
        'open_incident': GitHubIssueExecutor(live=live, client=github_client),
    }

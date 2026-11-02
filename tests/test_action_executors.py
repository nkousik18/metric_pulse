"""
Tests for the A4 executors (action_agent/executors.py): notify_owner through the notifier outbox,
and open_incident against a real local HTTP server that speaks the four GitHub REST calls the
executor uses. No mocks, no network beyond 127.0.0.1, nothing sent to GitHub.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.executors import (  # noqa: E402
    GitHubClient, GitHubError, GitHubIssueExecutor, NotifierExecutor, issue_marker, issue_number,
    owner_recipient,
)

OWNER = {'id': 'payments-team', 'name': 'Payments Team', 'email': 'payments@example.com', 'matched': 'dimension'}


def notify_dry_run(key='k' * 64):
    return {'action_type': 'notify_owner', 'anomaly_id': 'a' * 64, 'idempotency_key': key,
            'target': {'kind': 'notifier', 'channel': 'outbox', 'owner': OWNER},
            'payload': {'subject': '[MetricPulse] total_revenue anomaly', 'body': 'Revenue fell.\n\n| a | b |'}}


def incident_dry_run(key='i' * 64):
    return {'action_type': 'open_incident', 'anomaly_id': 'a' * 64, 'idempotency_key': key,
            'target': {'kind': 'github_issue', 'repo': 'acme/sandbox'},
            'payload': {'title': 'Credit card revenue collapse', 'labels': ['metricpulse', 'severity:high'],
                        'body': 'Evidence table here'}}


# --- notify_owner ---

def test_notify_owner_writes_an_outbox_message_to_the_resolved_owner(tmp_path):
    result = NotifierExecutor(channel='outbox', outbox_dir=tmp_path).execute(notify_dry_run())
    assert result['outcome'] == 'sent' and result['external_id'].startswith('outbox:')
    [index] = (tmp_path / 'index.jsonl').read_text().splitlines()
    line = json.loads(index)
    assert line['recipient'] == 'Payments Team <payments@example.com>'
    assert line['metadata'] == {'action': 'notify_owner', 'owner_id': 'payments-team',
                                'anomaly_id': 'a' * 64, 'idempotency_key': 'k' * 64}


def test_a_channel_that_leaves_the_machine_is_simulated_without_live(tmp_path):
    result = NotifierExecutor(live=False, channel='sns', outbox_dir=tmp_path).execute(notify_dry_run())
    assert result == {'outcome': 'simulated', 'external_id': None}
    assert list(tmp_path.iterdir()) == []


def test_owner_recipient_formats():
    assert owner_recipient({'name': 'A', 'email': 'a@x'}) == 'A <a@x>'
    assert owner_recipient({'id': 'oncall'}) == 'oncall'


# --- a local server for the GitHub REST calls ---

class FakeGitHub:
    def __init__(self, fail_create=False):
        self.issues, self.requests, self.fail_create = [], [], fail_create
        github = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                length = int(self.headers.get('Content-Length') or 0)
                return json.loads(self.rfile.read(length) or b'{}')

            def do_GET(self):
                url = urlparse(self.path)
                github.requests.append(('GET', url.path, parse_qs(url.query), self.headers.get('Authorization')))
                self._send(200, github.issues)

            def do_POST(self):
                body = self._body()
                github.requests.append(('POST', self.path, body, self.headers.get('Authorization')))
                if self.path.endswith('/comments'):
                    return self._send(201, {'id': 1})
                if github.fail_create:
                    return self._send(422, {'message': 'Validation Failed'})
                number = len(github.issues) + 1
                issue = {'number': number, 'state': 'open', 'html_url': f'https://github.com/acme/sandbox/issues/{number}',
                         **body}
                github.issues.append(issue)
                self._send(201, issue)

            def do_PATCH(self):
                body = self._body()
                github.requests.append(('PATCH', self.path, body, self.headers.get('Authorization')))
                number = int(self.path.rsplit('/', 1)[-1])
                github.issues[number - 1].update(body)
                self._send(200, github.issues[number - 1])

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'

    def client(self):
        return GitHubClient('acme/sandbox', 'test-token', api_url=self.url)

    def close(self):
        self.server.shutdown()


@pytest.fixture
def github():
    server = FakeGitHub()
    yield server
    server.close()


# --- open_incident ---

def test_open_incident_is_simulated_without_live(github):
    result = GitHubIssueExecutor(live=False, client=github.client()).execute(incident_dry_run())
    assert result == {'outcome': 'simulated', 'external_id': None} and github.requests == []


def test_open_incident_creates_one_issue_with_the_key_marker_and_labels(github):
    result = GitHubIssueExecutor(live=True, client=github.client()).execute(incident_dry_run())
    assert result == {'outcome': 'opened', 'external_id': 'https://github.com/acme/sandbox/issues/1'}
    [issue] = github.issues
    assert issue['title'] == 'Credit card revenue collapse'
    assert issue['labels'] == ['metricpulse', 'severity:high']
    assert issue['body'].endswith(issue_marker('i' * 64))
    assert all(r[3] == 'Bearer test-token' for r in github.requests)


def test_an_issue_that_already_carries_the_key_is_reused_not_duplicated(github):
    executor = GitHubIssueExecutor(live=True, client=github.client())
    first = executor.execute(incident_dry_run())
    second = executor.execute(incident_dry_run())    # e.g. a crash before `executed` was logged
    assert second == {'outcome': 'already_open', 'external_id': first['external_id']}
    assert len(github.issues) == 1


def test_a_different_key_opens_a_new_issue(github):
    executor = GitHubIssueExecutor(live=True, client=github.client())
    executor.execute(incident_dry_run('x' * 64))
    executor.execute(incident_dry_run('y' * 64))
    assert len(github.issues) == 2


def test_a_github_error_raises_so_the_graph_logs_execution_failed():
    server = FakeGitHub(fail_create=True)
    try:
        with pytest.raises(GitHubError, match='422'):
            GitHubIssueExecutor(live=True, client=server.client()).execute(incident_dry_run())
    finally:
        server.close()


def test_undo_closes_the_issue_with_a_comment(github):
    executor = GitHubIssueExecutor(live=True, client=github.client())
    url = executor.execute(incident_dry_run())['external_id']
    assert executor.undo(url, 'false alarm') == {'outcome': 'closed'}
    assert github.issues[0]['state'] == 'closed'
    comment = [r for r in github.requests if r[1].endswith('/comments')][0]
    assert comment[2] == {'body': 'Undone in MetricPulse: false alarm'}


def test_undo_of_a_real_issue_needs_live(github):
    with pytest.raises(RuntimeError, match='--live'):
        GitHubIssueExecutor(live=False, client=github.client()).undo('https://github.com/acme/sandbox/issues/3', 'r')


def test_undo_of_a_simulated_incident_has_nothing_to_close():
    assert GitHubIssueExecutor(live=False).undo(None, 'r') == {'outcome': 'nothing_to_close'}


def test_client_refuses_a_missing_repo_or_token():
    with pytest.raises(ValueError, match='owner/name'):
        GitHubClient(None, 'token')
    with pytest.raises(ValueError, match='GITHUB_TOKEN'):
        GitHubClient('acme/sandbox', None)


def test_issue_number_from_url():
    assert issue_number('https://github.com/acme/sandbox/issues/42') == 42

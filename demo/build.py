"""
Build the static replay site from the committed recordings (docs/hosting-scope.md §6.2, H1).

    python -m demo.build                   # -> demo/_site/ (gitignored)
    python -m demo.build --out /tmp/site
    python -m http.server -d demo/_site 8001   # then open http://127.0.0.1:8001/

Renders the SPA's real templates (templates/index.html and its partials) to one HTML page with
Django's template engine alone (no app settings, no database, no secrets, no LLM calls), with the
eval scorecard built from the recorded ledger (the same function the Django view uses), then adds:

- a banner saying the page replays real outputs, when and at which commit they were recorded;
- `replay.js` before the SPA's own script, so every /api/ call is answered from data/;
- the recordings themselves, copied to data/.

The SPA's own markup and JavaScript are not edited: each insertion point is an exact string that
must appear once, and the build fails if a template change moves it.
"""

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / 'demo' / 'recordings'
SITE_DIR = ROOT / 'demo' / '_site'
REPLAY_JS = ROOT / 'demo' / 'static' / 'replay.js'
TEMPLATES_DIR = ROOT / 'templates'
REPO_URL = 'https://github.com/nkousik18/metric_pulse'
# H2's demo-mode app (hosting-scope §6.5). None until it exists, so the site never links to nothing.
LIVE_URL = None

SCRIPTS_ANCHOR = '<script>\n    // Tab switching'
BODY_ANCHOR = '<body class="site">'


class BuildError(RuntimeError):
    pass


def render_spa(context: dict = None) -> str:
    from django.conf import settings
    if not settings.configured:
        settings.configure()
    from django.template import Context, Engine
    engine = Engine(dirs=[str(TEMPLATES_DIR)])
    return engine.get_template('index.html').render(Context(context or {}))


def recorded_scorecard(recordings: Path) -> dict:
    """The same scorecard the Django view builds, from the recorded ledger rows."""
    from observability.scorecard import scorecard_context
    evals = json.loads((recordings / 'evals' / 'latest.json').read_text())
    return scorecard_context({name: entry['latest'] for name, entry in evals.items()})


def insert_once(page: str, anchor: str, text: str, *, before: bool = True) -> str:
    if page.count(anchor) != 1:
        raise BuildError(f'expected exactly one {anchor!r} in the rendered SPA, found {page.count(anchor)}; '
                         'a template changed, so update the anchor in demo/build.py')
    return page.replace(anchor, text + anchor if before else anchor + text)


def banner(manifest: dict) -> str:
    date = manifest['recorded_at'][:10]
    sha = manifest['git_sha']
    live = (f' <a href="{html.escape(LIVE_URL)}">Try it live</a>'
            if LIVE_URL else
            f' To run it yourself, see the <a href="{REPO_URL}#readme">README</a>.')
    return f'''
    <div id="replay-banner" class="replay-banner">
        <div class="replay-banner-inner">
            Replaying real outputs recorded on <strong>{html.escape(date)}</strong>
            at commit <a href="{REPO_URL}/commit/{html.escape(sha.replace('-dirty', ''))}" class="mono">{html.escape(sha)}</a>.
            Nothing on this page calls a server or an LLM.{live}
        </div>
    </div>
'''


def build(recordings: Path = RECORDINGS_DIR, out: Path = SITE_DIR) -> Path:
    manifest_path = recordings / 'manifest.json'
    if not manifest_path.exists():
        raise BuildError(f'{manifest_path} is missing: run `python -m demo.record` first')
    manifest = json.loads(manifest_path.read_text())

    page = render_spa(recorded_scorecard(recordings))
    page = insert_once(page, BODY_ANCHOR, banner(manifest), before=False)
    page = insert_once(page, SCRIPTS_ANCHOR, '<script src="replay.js"></script>\n')

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / 'index.html').write_text(page)
    shutil.copy2(REPLAY_JS, out / 'replay.js')
    shutil.copytree(recordings, out / 'data')
    (out / '.nojekyll').write_text('')   # serve data/ as-is
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--recordings', type=Path, default=RECORDINGS_DIR)
    parser.add_argument('--out', type=Path, default=SITE_DIR)
    args = parser.parse_args(argv)
    try:
        out = build(args.recordings, args.out)
    except BuildError as e:
        sys.exit(str(e))
    print(f'Built {out} ({sum(1 for _ in out.rglob("*") if _.is_file())} files).')


if __name__ == '__main__':
    main()

/*
 * MetricPulse static replay (docs/hosting-scope.md §6.2, milestone H1).
 *
 * Loaded before templates/partials/scripts.html. Wraps window.fetch so every /api/ request the
 * unchanged SPA makes is answered from demo/recordings/ (copied to data/ by demo/build.py): real
 * responses recorded by `python -m demo.record`. A request that wasn't recorded gets an error
 * saying so, never a made-up answer (rule R1). Other requests go to the network as usual.
 *
 * The request key rules mirror demo/keys.py exactly; tests/test_demo_site.py runs both.
 */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;              // Node: the tests import the pure functions
    } else {
        api.install(root);
    }
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    const TOKEN_KEY = 'metricpulse.approverToken';   // scripts.html's APPROVER_TOKEN_KEY
    const VERB_LABEL = { approve: 'Approve', edit: 'Approve edited params', reject: 'Reject', undo: 'Undo' };

    // --- request keys (mirror of demo/keys.py) ---

    function normalizeQuery(path, name, value) {
        if (path === '/api/anomalies/' && name === 'threshold') return parseFloat(value).toFixed(1);
        return value;
    }

    function requestKey(method, url, body) {
        const parsed = new URL(url, 'http://replay.invalid');
        const path = parsed.pathname;
        const params = {};
        for (const [name, value] of parsed.searchParams) params[name] = normalizeQuery(path, name, value);
        for (const [name, value] of Object.entries(body || {})) params[name] = JSON.stringify(value);
        const query = Object.keys(params).sort().map(name => `${name}=${params[name]}`).join('&');
        return `${method.toUpperCase()} ${path}` + (query ? `?${query}` : '');
    }

    function canonical(value) {
        if (Array.isArray(value)) return value.map(canonical);
        if (value && typeof value === 'object') {
            return Object.keys(value).sort().reduce((out, k) => { out[k] = canonical(value[k]); return out; }, {});
        }
        return value;
    }

    function sameJson(a, b) {
        return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
    }

    // --- the Action Agent walk-through: recorded steps, in order ---

    function createActionReplay(flow) {
        let cursor = 0;
        let state = flow.initial;

        function nextStep() { return flow.steps[cursor] || null; }

        function describe(step) {
            return `${VERB_LABEL[step.verb]} on proposal ${step.proposal_id.slice(0, 8)}`;
        }

        // -> {status, body} for a recorded answer, or {notRecorded: message}.
        function handle(method, url, body) {
            const path = new URL(url, 'http://replay.invalid').pathname;
            if (method === 'GET' && path === '/api/actions/pending/') return { status: 200, body: state.pending };
            if (method === 'GET' && path === '/api/actions/log/') return { status: 200, body: state.log };
            const match = method === 'POST' && path.match(/^\/api\/actions\/([^/]+)\/(approve|edit|reject|undo)\/$/);
            if (!match) return { notRecorded: `${method} ${path} wasn't recorded.` };
            const [, proposalId, verb] = match;
            body = body || {};
            if (body.live === true) {
                return { notRecorded: 'This walk-through was recorded with live effects off. Untick "Allow effects outside this machine".' };
            }
            if ((verb === 'reject' || verb === 'undo') && !String(body.reason || '').trim()) {
                const v = flow.validation[verb];
                return { status: v.status, body: v.body };    // the real API's answer to a missing reason
            }
            const step = nextStep();
            if (!step) return { notRecorded: 'The recorded walk-through is complete. Reload the page to replay it.' };
            if (step.proposal_id !== proposalId || step.verb !== verb) {
                return { notRecorded: `This replay follows the recorded order. Next recorded step: ${describe(step)}.` };
            }
            if (String(body.reason || '').trim() !== step.body.reason) {
                return { notRecorded: `The recording used the reason "${step.body.reason}" (pre-filled on the card).` };
            }
            if (verb === 'edit' && !sameJson(body.params, step.body.params)) {
                return { notRecorded: 'The recording approved specific edited params (pre-filled on the card).' };
            }
            cursor += 1;
            state = step.after;
            return { status: step.response.status, body: step.response.body };
        }

        return { handle, nextStep, describe };
    }

    // --- browser install ---

    function install(window) {
        const document = window.document;
        const realFetch = window.fetch.bind(window);
        const dataBase = new URL('data/', document.baseURI);
        const cache = new Map();

        function getJson(rel) {
            if (!cache.has(rel)) {
                cache.set(rel, realFetch(new URL(rel, dataBase)).then(r => {
                    if (!r.ok) throw new Error(`missing recording ${rel}`);
                    return r.json();
                }));
            }
            return cache.get(rel);
        }

        const ready = Promise.all([getJson('index.json'), getJson('manifest.json'), getJson('actions/flow.json')])
            .then(([index, manifest, flow]) => ({ index, manifest, actions: createActionReplay(flow) }));

        // The recorded AI investigations join Investigate's "Days to look at" list
        // (templates/partials/scripts.html reads window.extraFlaggedDays).
        ready.then(({ manifest }) => {
            window.extraFlaggedDays = (manifest.investigations || []).map(c => ({
                date: c.current_date, previous_date: c.previous_date, metric: c.metric, investigate: true,
                note: `AI investigation recorded \u00b7 labelled ${c.labelled_event ? 'an event' : 'not an event'}`,
            }));
            if (typeof window.renderFlaggedDays === 'function') window.renderFlaggedDays();
        });

        try {
            if (!window.sessionStorage.getItem(TOKEN_KEY)) window.sessionStorage.setItem(TOKEN_KEY, 'static-replay');
        } catch (e) { /* private mode: the actions tab asks for a token; any value works here */ }

        function respond(payload, status) {
            return new window.Response(JSON.stringify(payload), {
                status, headers: { 'Content-Type': 'application/json' },
            });
        }

        function notRecorded(message) {
            showNotice(message);
            return respond({ status: 'error', message: `Not recorded: ${message}` }, 404);
        }

        window.fetch = async function (input, init) {
            init = init || {};
            const url = typeof input === 'string' ? input : input.url;
            if (!url.startsWith('/api/')) return realFetch(input, init);
            const { index, actions } = await ready;
            const method = (init.method || 'GET').toUpperCase();
            let body = null;
            if (init.body) { try { body = JSON.parse(init.body); } catch (e) { body = null; } }

            if (url.startsWith('/api/contact/')) {
                return notRecorded('The contact form is off on this static demo. Use the LinkedIn or GitHub links instead.');
            }
            if (url.startsWith('/api/actions/')) {
                const answer = actions.handle(method, url, body);
                if (answer.notRecorded) return notRecorded(answer.notRecorded);
                setTimeout(annotateActions, 0);
                return respond(answer.body, answer.status);
            }
            const entry = index[requestKey(method, url, body)];
            if (!entry) return notRecorded(hintFor(url));
            return respond(await getJson(entry.file), entry.status);
        };

        function hintFor(url) {
            if (url.startsWith('/api/investigate/')) {
                return 'AI investigations were recorded for three days only: the ones marked "AI investigation recorded" under Days to look at.';
            }
            if (url.startsWith('/api/decomposition/') || url.startsWith('/api/narrative/')) {
                return 'Breakdowns were recorded for each day against the day before it. Pick a consecutive pair of dates.';
            }
            return 'This demo replays recorded runs only.';
        }

        // --- in-page notice for unrecorded requests ---

        function showNotice(message) {
            let el = document.getElementById('replay-notice');
            if (!el) {
                el = document.createElement('div');
                el.id = 'replay-notice';
                el.setAttribute('role', 'status');
                el.className = 'fixed bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-xl w-[calc(100%-2rem)] bg-gray-900 text-white text-sm rounded-xl shadow-lg px-4 py-3';
                document.body.appendChild(el);
            }
            el.textContent = `This demo replays recorded runs. ${message}`;
            el.hidden = false;
            clearTimeout(showNotice.timer);
            showNotice.timer = setTimeout(() => { el.hidden = true; }, 7000);
        }

        // --- the Pending actions tab: mark the next recorded step on its card ---

        function annotateActions() {
            ready.then(({ actions }) => {
                const step = actions.nextStep();
                const guide = document.getElementById('replay-actions-guide');
                const text = step
                    ? `Next recorded step: ${actions.describe(step)}. Its reason${step.verb === 'edit' ? ' and edited params are' : ' is'} pre-filled on the card.`
                    : 'The recorded walk-through is complete. Reload the page to replay it.';
                if (guide && guide.textContent !== text) guide.textContent = text;   // no mutation unless it changed
                document.querySelectorAll('.replay-next').forEach(b => b.classList.remove('replay-next', 'ring-4', 'ring-amber-300'));
                if (!step) return;
                const id = step.proposal_id;
                const reasonId = step.verb === 'undo' ? `undo-reason-${id}` : `reason-${id}`;
                const reason = document.getElementById(reasonId);
                if (reason && !reason.value) reason.value = step.body.reason;
                if (step.verb === 'edit') {
                    const params = document.getElementById(`params-${id}`);
                    if (params) params.value = JSON.stringify(step.body.params, null, 2);
                }
                const call = step.verb === 'undo' ? `undoAction('${id}')` : `decideAction('${id}', '${step.verb}')`;
                const button = document.querySelector(`button[onclick="${call}"]`);
                if (button) button.classList.add('replay-next', 'ring-4', 'ring-amber-300');
            });
        }

        // --- the Recorded runs tab ---

        function esc(value) {
            return String(value ?? '').replace(/[&<>"']/g, c => (
                { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
        }

        function fmtMetric(m) {
            if (!m || m.value === null || m.value === undefined) return 'n/a';
            const v = typeof m.value === 'number' && !Number.isInteger(m.value) ? m.value.toFixed(m.value < 0.01 ? 5 : 2) : m.value;
            return m.num !== null && m.num !== undefined && Number.isInteger(m.num) && m.n ? `${v} (${m.num}/${m.n})` : `${v}`;
        }

        async function waitFor(test, timeoutMs) {
            const end = Date.now() + (timeoutMs || 10000);
            while (Date.now() < end) {
                if (test()) return true;
                await new Promise(r => setTimeout(r, 100));
            }
            return false;
        }

        async function openCase(i) {
            const { manifest } = await ready;
            const c = manifest.investigations[i];
            window.showTab('dashboard');
            const found = await waitFor(() => document.querySelector(`#current-date option[value="${c.current_date}"]`));
            if (!found) { showNotice('The dashboard dates did not load.'); return; }
            window.selectMetric(c.metric);
            document.getElementById('current-date').value = c.current_date;
            document.getElementById('previous-date').value = c.previous_date;
            window.applyFilters();
            const block = document.getElementById('investigate-btn');
            if (block) block.scrollIntoView({ behavior: 'smooth', block: 'center' });
            window.investigateWithAgent();
        }
        window.replayOpenCase = openCase;

        function renderOnboarding(o) {
            const clf = o.classification.classification;
            const dims = clf.dimension_columns.map(d => `<li>${esc(d.column)} <span class="text-gray-400">(${esc(d.cardinality)} values, confidence ${esc(d.confidence)})</span></li>`).join('');
            const rejected = clf.rejected_columns.map(r => `<li>${esc(r.column)}: <span class="text-gray-500">${esc(r.reason)}</span></li>`).join('');
            const rows = Object.entries(o.results).map(([metric, r]) => `
                <tr class="border-t border-gray-100 align-top">
                    <td class="px-3 py-2 font-medium">${esc(metric)}</td>
                    <td class="px-3 py-2 whitespace-nowrap">${esc(r.current_date)} vs ${esc(r.previous_date)}</td>
                    <td class="px-3 py-2">${esc(r.detection.anomaly_count)}</td>
                    <td class="px-3 py-2 text-gray-700">${esc(r.narratives.summary)}</td>
                </tr>`).join('');
            return `
                <div class="grid md:grid-cols-2 gap-6 mb-6">
                    <div>
                        <p class="text-sm text-gray-700 mb-2"><strong>Date column:</strong> ${esc(clf.date_column)} · <strong>Metrics:</strong> ${esc(clf.metric_columns.join(', '))}</p>
                        <p class="text-sm font-semibold text-gray-700">Dimensions it chose</p>
                        <ul class="list-disc ml-5 text-sm text-gray-700">${dims}</ul>
                    </div>
                    <div>
                        <p class="text-sm font-semibold text-gray-700">Columns it rejected, and why</p>
                        <ul class="list-disc ml-5 text-sm text-gray-700">${rejected}</ul>
                    </div>
                </div>
                <div class="overflow-x-auto"><table class="w-full text-sm">
                    <thead><tr class="text-left text-gray-500"><th class="px-3 py-2">Metric</th><th class="px-3 py-2">Dates</th><th class="px-3 py-2">Anomalies</th><th class="px-3 py-2">Narrative (same pipeline as Olist)</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }

        function renderEvals(evals) {
            return Object.entries(evals).map(([name, e]) => {
                const metrics = Object.entries(e.latest.metrics).map(([k, m]) => `
                    <tr class="border-t border-gray-100"><td class="px-3 py-1.5 font-mono text-xs">${esc(k)}</td><td class="px-3 py-1.5">${esc(fmtMetric(m))}</td></tr>`).join('');
                return `
                <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
                    <h4 class="font-semibold text-gray-900 capitalize">${esc(name)}</h4>
                    <p class="text-xs text-gray-500 mb-2">${esc(e.latest.ts)} · commit ${esc(e.latest.git_sha)}</p>
                    <table class="w-full text-sm"><tbody>${metrics}</tbody></table>
                </div>`;
            }).join('');
        }

        async function renderRecorded() {
            const rootEl = document.getElementById('recorded-root');
            if (!rootEl) return;
            try {
                const { manifest } = await ready;
                const [onboarding, evals] = await Promise.all([
                    getJson('onboarding/superstore_sales.json'), getJson('evals/latest.json')]);
                rootEl.innerHTML = `
                    <section class="mb-10">
                        <h3 class="text-xl font-bold text-gray-900 mb-1">Dataset onboarding: Superstore</h3>
                        <p class="text-sm text-gray-600 mb-4">A CSV the pipeline had never seen. The onboarding agent classified its columns (confirmed by a human), generated the tables, and the unchanged detect, decompose and narrate pipeline ran on it.</p>
                        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">${renderOnboarding(onboarding)}</div>
                    </section>
                    <section class="mb-4">
                        <h3 class="text-xl font-bold text-gray-900 mb-1">Evals: the latest run of each</h3>
                        <p class="text-sm text-gray-600 mb-4">From <code>evals/ledger.jsonl</code>; <code>python -m observability.drift --report</code> prints the same numbers.</p>
                        <div class="grid md:grid-cols-2 gap-4">${renderEvals(evals)}</div>
                    </section>`;
            } catch (error) {
                rootEl.textContent = `The recordings did not load: ${error.message}`;
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            const contact = document.getElementById('contact-name');
            const form = contact && contact.closest('.max-w-xl');
            if (form) {
                form.innerHTML = '<p class="text-sm text-gray-600">The contact form is off on this static demo. The GitHub and LinkedIn links in the footer reach me.</p>';
            }
            const pending = document.getElementById('pending-actions');
            if (pending) {
                const guide = document.createElement('div');
                guide.id = 'replay-actions-guide';
                guide.className = 'bg-amber-50 border border-amber-200 text-amber-900 text-sm rounded-xl p-4 mb-4';
                guide.textContent = 'This tab replays a recorded approval flow: approve, edit, reject, then undo, all with live effects off.';
                pending.parentNode.insertBefore(guide, pending);
                // Watch only the two card lists the SPA re-renders. The guide lives outside them, so
                // annotateActions() writing to it can't re-trigger this observer (no feedback loop).
                const observer = new window.MutationObserver(() => annotateActions());
                for (const id of ['pending-actions', 'undoable-actions']) {
                    const el = document.getElementById(id);
                    if (el) observer.observe(el, { childList: true });
                }
            }
            renderRecorded();
        });
    }

    return { requestKey, canonical, sameJson, createActionReplay, install };
});

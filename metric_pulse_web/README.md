# metric_pulse_web/

The Django project package — settings, root URL routing, and WSGI/ASGI entry points. This is project-level wiring, not application code; the actual API logic lives in `dashboard_api/` and the actual pipeline logic lives in `detection/`, `decomposition/`, `narrative/`, `orchestration/`.

## File inventory

| File | Purpose |
|------|---------|
| `settings.py` | Base Django settings, active for local development (`DJANGO_DEBUG=True` by default) |
| `settings_prod.py` | Production overrides for Render — `from .settings import *` then overrides 4 settings |
| `urls.py` | Root URL configuration — 3 routes total |
| `wsgi.py` | WSGI entry point, used by Gunicorn in production (`gunicorn metric_pulse_web.wsgi:application`) |
| `asgi.py` | ASGI entry point — present for completeness/future use; nothing in this project uses async views or channels, so this file is currently unused in practice |
| `__init__.py` | Empty package marker |

## `settings.py` — key values (verified against source)

| Setting | Value | Source |
|---------|-------|--------|
| `SECRET_KEY` | `os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key-change-in-production')` | falls back to a hardcoded dev key if env var unset |
| `DEBUG` | `os.getenv('DJANGO_DEBUG', 'True') == 'True'` | defaults **on** |
| `ALLOWED_HOSTS` | `['localhost', '127.0.0.1', '*']` | wildcard is present even in the base file — only `settings_prod.py` removes it |
| `INSTALLED_APPS` | admin, auth, contenttypes, sessions, messages, staticfiles, `rest_framework`, `corsheaders`, `dashboard_api` | |
| `MIDDLEWARE` | `corsheaders.CorsMiddleware` is **first**, ahead of Django's `SecurityMiddleware` | required by django-cors-headers |
| `ROOT_URLCONF` | `'metric_pulse_web.urls'` | |
| `TEMPLATES[0].DIRS` | `[BASE_DIR / 'templates']` | points at the top-level `templates/` folder, not an app-local one |
| `DATABASES` | SQLite at `BASE_DIR / 'db.sqlite3'` | Django auth/sessions/admin only — no business data ever lands here; all analytics data lives in Redshift |
| `STATIC_URL` / `STATICFILES_DIRS` / `STATIC_ROOT` | `static/` → `static/` (source) → `staticfiles/` (collectstatic target) | |
| `CORS_ALLOW_ALL_ORIGINS` | `= DEBUG` | wide open in dev, closed in prod (no explicit prod allow-list is set anywhere, so in prod CORS effectively blocks all cross-origin requests — the SPA is same-origin on Render so this is fine) |
| `REST_FRAMEWORK` | `DEFAULT_RENDERER_CLASSES`: `JSONRenderer`, `BrowsableAPIRenderer` | the browsable API UI is reachable at any `/api/*` URL in a browser |
| `EMAIL_*` | Gmail SMTP (`smtp.gmail.com:587`, TLS), credentials from `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | configured but currently **unused** — see `dashboard_api/README.md`, `ContactView`'s `send_mail()` call is commented out |

## `settings_prod.py` — overrides (full diff from base)

```python
from .settings import *
DEBUG = False
ALLOWED_HOSTS = ['.onrender.com']
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')   # position 1, right after CORS
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

Activated only when `DJANGO_SETTINGS_MODULE=metric_pulse_web.settings_prod` is set (done in `render.yaml` for the live deployment). `wsgi.py`/`asgi.py` both hardcode the **base** `settings` module as their `setdefault` fallback — Render's env var is what actually switches them to `settings_prod`.

## `urls.py` — full route table

```python
path('admin/', admin.site.urls)
path('api/', include('dashboard_api.urls'))          # → all 7 endpoints in dashboard_api/urls.py
path('', TemplateView.as_view(template_name='index.html'), name='home')
```

That's it — every non-`/admin`, non-`/api` request serves `templates/index.html` (which just extends `base.html` — see `templates/README.md`). There is no `404.html`/`500.html` override and no catch-all route beyond `/`.

## Running standalone

```bash
python manage.py migrate      # creates db.sqlite3 for sessions/admin — first run only
python manage.py runserver    # → http://127.0.0.1:8000, uses settings.py (dev)
```

To exercise the prod settings locally:
```bash
DJANGO_SETTINGS_MODULE=metric_pulse_web.settings_prod python manage.py runserver
```
(will fail without `whitenoise` and Render's `.onrender.com` host — mainly useful for `collectstatic` dry-runs, not for actually serving locally.)

## Env vars this package reads directly

`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` (all via `python-dotenv`'s `load_dotenv()` called at the top of `settings.py`).

## Gotchas

- `ALLOWED_HOSTS = ['*']` is baked into the **base** `settings.py`, not just a Render-specific mistake — it's fine because `DEBUG=True` is also the dev default, but if someone ran the base settings module in a real prod-like environment without switching to `settings_prod`, the wildcard host would go live too.
- `asgi.py` exists but nothing in the project uses it — Gunicorn's WSGI entry point (`wsgi.py`) is what Render actually runs (see `Procfile`/`render.yaml`).
- Static files: `STATICFILES_DIRS` points at a mostly-empty `static/` folder (custom assets, if any); the SPA's actual CSS/JS comes from CDN links in `templates/base.html`, not from Django-served static files.

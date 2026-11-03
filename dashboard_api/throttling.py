"""
Request throttling for the endpoints that cost money or change state (docs/action-agent-scope.md N4).

DRF's ScopedRateThrottle copies DEFAULT_THROTTLE_RATES into a class attribute when the module is
imported, so changing the rates later (override_settings in a test, say) has no effect. This
subclass reads them from Django settings on every request instead. Each view names its scope
with `throttle_scope`; clients are told apart by IP address, and counts live in Django's default
cache (local memory, per process, which is enough for a local, single-process app, D9).
"""

from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class ScopedThrottle(ScopedRateThrottle):
    def get_rate(self):
        rates = getattr(settings, 'REST_FRAMEWORK', {}).get('DEFAULT_THROTTLE_RATES', {})
        return rates.get(self.scope)


class ThrottleFirstMixin:
    """Check throttles before authentication and permissions, so failed attempts count too.

    DRF's default order is authenticate -> permissions -> throttles, which means a request
    with a wrong approver token is refused before it is counted, and guessing the token
    would never be rate limited."""

    def initial(self, request, *args, **kwargs):
        self.format_kwarg = self.get_format_suffix(**kwargs)
        neg = self.perform_content_negotiation(request)
        request.accepted_renderer, request.accepted_media_type = neg
        version, scheme = self.determine_version(request, *args, **kwargs)
        request.version, request.versioning_scheme = version, scheme
        self.check_throttles(request)
        self.perform_authentication(request)
        self.check_permissions(request)

"""
The single page (templates/index.html). Its only server-side data is the eval scorecard
(observability/scorecard.py), read from evals/ledger.jsonl at request time; every other number
on the page comes from the /api/ calls in partials/scripts.html.
"""

import logging

from django.views.generic import TemplateView

logger = logging.getLogger(__name__)


def latest_scorecard():
    """The scorecard from the latest ledger rows, or None if the ledger can't be read (the page
    then renders without it, never fails: the try/except-never-raise convention)."""
    try:
        from observability.drift import latest_rows
        from observability.evals import read_ledger
        from observability.scorecard import build_scorecard
        return build_scorecard(latest_rows(read_ledger()))
    except Exception as e:
        logger.warning(f'eval scorecard unavailable: {e}')
        return None


class HomeView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['scorecard'] = latest_scorecard()
        return context

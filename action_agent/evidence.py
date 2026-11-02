"""
Evidence for the Action Agent, built the same way the pipeline builds it: comparison dates,
decompose_metric, the deterministic narrative and the top driver. Shared by the CLI's `propose`
and by probe.py, so both see exactly the evidence a pipeline run would.

Datasets: `olist` (the local DuckDB warehouse since local-stack L1, or Redshift under
WAREHOUSE=redshift) and any onboarded dataset (Phase 2, its own DuckDB file).
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.identity import OLIST_DATASET_ID  # noqa: E402
from action_agent.runner import to_plain  # noqa: E402
from config.db import get_connection  # noqa: E402


def dataset_config(dataset_id: str) -> Dict:
    if dataset_id == OLIST_DATASET_ID:
        return {'metric_columns': None, 'table_name': 'staging.fact_daily_metrics',
                'connection_factory': get_connection, 'dimension_config': None}
    from onboarding.investigate import load_dataset_config
    config, _ = load_dataset_config(dataset_id)
    return config


def top_anomaly_dates(dataset_id: str, metric: str, n: int) -> List[str]:
    from detection.anomaly_detector import detect_anomalies, fetch_daily_metrics
    cfg = dataset_config(dataset_id)
    df = fetch_daily_metrics(100_000, cfg['metric_columns'], cfg['table_name'], cfg['connection_factory'])
    df = detect_anomalies(df, metric)
    df = df[df['is_anomaly']].assign(absz=lambda d: d['zscore'].abs())
    df = df.sort_values(['absz', 'metric_date'], ascending=[False, True])
    return [str(d)[:10] for d in df['metric_date'].head(n)]


def require_decomposable(evidence: Dict, dataset_id: str, metric: str) -> None:
    """Raise a clear ValueError when no dimension could be decomposed for this metric (every
    dimension came back as an error). Without it the narrative generator fails with a bare
    KeyError: e.g. Olist's `customer_count` is in the daily fact table but in none of the
    per-dimension tables, which only carry total_revenue and order_count."""
    dims = evidence.get('dimensions') or {}
    if dims and all('error' in d for d in dims.values()):
        first = next(iter(dims.values()))['error']
        raise ValueError(f"{dataset_id}/{metric} can't be decomposed by segment: no dimension table has "
                         f"that metric ({first[:120]})")


def build_case(dataset_id: str, metric: str, target_date: Optional[str] = None) -> Dict:
    """Evidence for one anomaly, exactly as the pipeline builds it. target_date=None means the
    latest date in the data (what `propose` and the pipeline use)."""
    from decomposition.decomposer import decompose_metric, get_comparison_dates, get_top_driver
    from narrative.generator import generate_narrative
    cfg = dataset_config(dataset_id)
    current, previous = get_comparison_dates(target_date, table_name=cfg['table_name'],
                                             connection_factory=cfg['connection_factory'])
    kwargs = {'connection_factory': cfg['connection_factory']}
    if cfg['dimension_config'] is not None:
        kwargs['dimension_config'] = cfg['dimension_config']
    evidence = to_plain(decompose_metric(current, previous, metric, **kwargs))
    require_decomposable(evidence, dataset_id, metric)
    return {'dataset_id': dataset_id, 'metric': metric, 'anomaly_date': current,
            'evidence': evidence, 'narrative_summary': generate_narrative(evidence)['summary'],
            'top_driver': to_plain(get_top_driver(evidence))}

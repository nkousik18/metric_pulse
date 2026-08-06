"""
Main orchestration pipeline for MetricPulse.
Runs anomaly detection, decomposition, and alerting end-to-end.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import argparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger
from detection.anomaly_detector import run_detection, fetch_daily_metrics
from decomposition.decomposer import decompose_metric, get_comparison_dates
from narrative.generator import generate_narrative
from alerting.sns_publisher import publish_metric_alert

load_dotenv()

logger = setup_logger(__name__)


def run_pipeline(
    metric: str = 'total_revenue',
    threshold: float = None,
    force_alert: bool = False,
    dry_run: bool = False,
    publish_metrics: bool = True,
    run_investigation: bool = False
) -> Dict:
    """
    Run the full MetricPulse pipeline.

    Args:
        metric: Metric to analyze
        threshold: Z-score threshold for anomaly detection
        force_alert: Send alert even if no anomaly detected
        dry_run: Skip actual alert sending
        publish_metrics: Publish metrics to CloudWatch
        run_investigation: Run the Phase 1 investigation agent (docs/scoping.md
            Section 4.2) after narrative generation, before alerting. Default
            False -- zero behavior change for every existing caller.

    Returns:
        Pipeline results
    """
    logger.info("=" * 60)
    logger.info("METRICPULSE PIPELINE STARTED")
    logger.info("=" * 60)
    
    start_time = datetime.now()
    
    results = {
        'started_at': start_time.isoformat(),
        'metric': metric,
        'status': 'running'
    }
    
    try:
        # Step 1: Anomaly Detection
        logger.info("Step 1: Running anomaly detection...")
        detection_results = run_detection(metric=metric, threshold=threshold)
        results['detection'] = detection_results
        
        anomaly_detected = detection_results['anomaly_count'] > 0
        logger.info(f"Anomalies detected: {detection_results['anomaly_count']}")
        
        # Step 2: Get comparison dates
        logger.info("Step 2: Getting comparison dates...")
        current_date, previous_date = get_comparison_dates()
        results['current_date'] = current_date
        results['previous_date'] = previous_date
        logger.info(f"Comparing: {previous_date} → {current_date}")
        
        # Step 3: Decomposition
        logger.info("Step 3: Running decomposition...")
        decomposition_results = decompose_metric(current_date, previous_date, metric)
        results['decomposition'] = decomposition_results
        
        # Step 4: Generate Narrative
        logger.info("Step 4: Generating narrative...")
        narratives = generate_narrative(decomposition_results)
        results['narratives'] = narratives

        # Step 4.5: Investigation agent (optional, non-blocking) -- only when
        # there's something worth investigating, mirroring the alert gate below.
        # Imported locally, not at module top, so every existing caller that
        # doesn't request this never pays LangGraph/Groq import weight or needs
        # GROQ_API_KEY set (same lazy-import convention this file already uses
        # for monitoring.cloudwatch_metrics below).
        if run_investigation and (anomaly_detected or force_alert):
            logger.info("Step 4.5: Running investigation agent...")
            try:
                from investigation.graph import investigation_graph
                from investigation.state import build_initial_state

                initial_state = build_initial_state(
                    metric=metric,
                    threshold=threshold,
                    force_investigate=force_alert,
                    current_date=current_date,
                    previous_date=previous_date,
                    detection_result=detection_results,
                    decomposition_results=decomposition_results,
                )
                final_state = investigation_graph.invoke(initial_state)
                results['investigation'] = {
                    'status': final_state['status'],
                    'investigation_summary': final_state.get('investigation_summary'),
                    'grounding_failed': final_state.get('grounding_failed', False),
                }
                logger.info(f"Investigation status: {results['investigation']['status']}")
            except Exception as e:
                logger.warning(f"Investigation agent failed (non-blocking): {e}")
                results['investigation'] = {'status': 'failed', 'error': str(e)}

        # Step 5: Send Alert (if anomaly detected or forced)
        if anomaly_detected or force_alert:
            logger.info("Step 5: Sending alert...")
            
            if dry_run:
                logger.info("DRY RUN - Alert not sent")
                results['alert'] = {'status': 'dry_run'}
            else:
                alert_result = publish_metric_alert(narratives)
                results['alert'] = alert_result
                logger.info(f"Alert status: {alert_result['status']}")
        else:
            logger.info("Step 5: No anomaly detected, skipping alert")
            results['alert'] = {'status': 'skipped', 'reason': 'no_anomaly'}
        
        results['status'] = 'completed'
        results['completed_at'] = datetime.now().isoformat()
        results['duration_seconds'] = (datetime.now() - start_time).total_seconds()
        
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        results['status'] = 'failed'
        results['error'] = str(e)
        results['duration_seconds'] = (datetime.now() - start_time).total_seconds()
    
    # Publish metrics to CloudWatch
    if publish_metrics and not dry_run:
        try:
            from monitoring.cloudwatch_metrics import publish_pipeline_metrics
            publish_pipeline_metrics(results)
            logger.info("Published metrics to CloudWatch")
        except Exception as e:
            logger.warning(f"Failed to publish CloudWatch metrics: {e}")
    
    return results


def print_summary(results: Dict):
    """Print human-readable pipeline summary."""
    print("\n" + "=" * 60)
    print("METRICPULSE PIPELINE SUMMARY")
    print("=" * 60)
    
    print(f"\nStatus: {results['status'].upper()}")
    print(f"Metric: {results['metric']}")
    print(f"Period: {results.get('previous_date', 'N/A')} → {results.get('current_date', 'N/A')}")
    print(f"Duration: {results.get('duration_seconds', 0):.2f}s")
    
    if 'detection' in results:
        d = results['detection']
        print(f"\nAnomaly Detection:")
        print(f"  Days analyzed: {d.get('total_days_analyzed', 'N/A')}")
        print(f"  Anomalies found: {d.get('anomaly_count', 0)}")
    
    if 'narratives' in results:
        print(f"\nSummary:")
        print(f"  {results['narratives'].get('summary', 'N/A')}")

    if 'investigation' in results:
        inv = results['investigation']
        print(f"\nInvestigation Agent:")
        print(f"  Status: {inv.get('status', 'N/A')}")
        if inv.get('investigation_summary'):
            print(f"  Summary: {inv['investigation_summary']}")
        if inv.get('grounding_failed'):
            print(f"  (fell back to deterministic summary -- grounding failed)")
        if inv.get('error'):
            print(f"  Error: {inv['error']}")

    if 'alert' in results:
        a = results['alert']
        print(f"\nAlert Status: {a.get('status', 'N/A')}")
        if a.get('message_id'):
            print(f"  Message ID: {a['message_id']}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='MetricPulse Pipeline')
    parser.add_argument('--metric', type=str, default='total_revenue', help='Metric to analyze')
    parser.add_argument('--threshold', type=float, default=None, help='Z-score threshold')
    parser.add_argument('--force-alert', action='store_true', help='Send alert even without anomaly')
    parser.add_argument('--dry-run', action='store_true', help='Skip sending actual alert')
    parser.add_argument('--no-metrics', action='store_true', help='Skip CloudWatch metrics')
    parser.add_argument('--run-investigation', action='store_true', help='Run the investigation agent')

    args = parser.parse_args()

    try:
        results = run_pipeline(
            metric=args.metric,
            threshold=args.threshold,
            force_alert=args.force_alert,
            dry_run=args.dry_run,
            publish_metrics=not args.no_metrics,
            run_investigation=args.run_investigation
        )
        print_summary(results)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)

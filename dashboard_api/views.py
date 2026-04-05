"""
API views for MetricPulse dashboard.
"""

import sys
from pathlib import Path
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from detection.anomaly_detector import run_detection, fetch_daily_metrics
from decomposition.decomposer import decompose_metric, get_comparison_dates
from narrative.generator import generate_narrative
from orchestration.run_pipeline import run_pipeline


class HealthCheckView(APIView):
    """Health check endpoint."""
    
    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'MetricPulse API',
            'timestamp': datetime.now().isoformat()
        })


class MetricsListView(APIView):
    """Get daily metrics data."""
    
    def get(self, request):
        try:
            lookback = int(request.query_params.get('days', 30))
            df = fetch_daily_metrics(lookback)
            
            data = df.to_dict('records')
            
            # Convert dates to strings
            for row in data:
                if 'metric_date' in row:
                    row['metric_date'] = str(row['metric_date'])
            
            return Response({
                'status': 'success',
                'count': len(data),
                'data': data
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AnomalyDetectionView(APIView):
    """Run anomaly detection."""
    
    def get(self, request):
        try:
            metric = request.query_params.get('metric', 'total_revenue')
            threshold = request.query_params.get('threshold')
            
            if threshold:
                threshold = float(threshold)
            
            results = run_detection(metric=metric, threshold=threshold)
            
            return Response({
                'status': 'success',
                'data': results
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DecompositionView(APIView):
    """Run metric decomposition."""
    
    def get(self, request):
        try:
            current_date = request.query_params.get('current_date')
            previous_date = request.query_params.get('previous_date')
            metric = request.query_params.get('metric', 'total_revenue')
            
            if not current_date or not previous_date:
                current_date, previous_date = get_comparison_dates()
            
            results = decompose_metric(current_date, previous_date, metric)
            
            return Response({
                'status': 'success',
                'data': results
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NarrativeView(APIView):
    """Generate narrative from decomposition."""
    
    def get(self, request):
        try:
            current_date = request.query_params.get('current_date')
            previous_date = request.query_params.get('previous_date')
            
            if not current_date or not previous_date:
                current_date, previous_date = get_comparison_dates()
            
            decomposition = decompose_metric(current_date, previous_date)
            narratives = generate_narrative(decomposition)
            
            return Response({
                'status': 'success',
                'data': narratives
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PipelineView(APIView):
    """Run full pipeline."""
    
    def post(self, request):
        try:
            metric = request.data.get('metric', 'total_revenue')
            force_alert = request.data.get('force_alert', False)
            dry_run = request.data.get('dry_run', True)
            
            results = run_pipeline(
                metric=metric,
                force_alert=force_alert,
                dry_run=dry_run,
                publish_metrics=False
            )
            
            return Response({
                'status': 'success',
                'data': {
                    'pipeline_status': results['status'],
                    'metric': results['metric'],
                    'anomaly_count': results.get('detection', {}).get('anomaly_count', 0),
                    'alert_status': results.get('alert', {}).get('status'),
                    'summary': results.get('narratives', {}).get('summary', ''),
                    'duration_seconds': results.get('duration_seconds', 0)
                }
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

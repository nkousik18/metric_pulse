from django.urls import path
from .views import (
    HealthCheckView,
    MetricsListView,
    AnomalyDetectionView,
    DecompositionView,
    NarrativeView,
    PipelineView,
    ContactView
)

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('metrics/', MetricsListView.as_view(), name='metrics'),
    path('anomalies/', AnomalyDetectionView.as_view(), name='anomalies'),
    path('decomposition/', DecompositionView.as_view(), name='decomposition'),
    path('narrative/', NarrativeView.as_view(), name='narrative'),
    path('pipeline/', PipelineView.as_view(), name='pipeline'),
    path('contact/', ContactView.as_view(), name='contact'),
]

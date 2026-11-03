from django.urls import path
from .views import (
    HealthCheckView,
    MetricsListView,
    AnomalyDetectionView,
    DecompositionView,
    NarrativeView,
    PipelineView,
    InvestigationView,
    ContactView
)
from .action_views import (
    PendingActionsView,
    ActionLogView,
    ApproveActionView,
    EditActionView,
    RejectActionView,
    UndoActionView,
)

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('metrics/', MetricsListView.as_view(), name='metrics'),
    path('anomalies/', AnomalyDetectionView.as_view(), name='anomalies'),
    path('decomposition/', DecompositionView.as_view(), name='decomposition'),
    path('narrative/', NarrativeView.as_view(), name='narrative'),
    path('pipeline/', PipelineView.as_view(), name='pipeline'),
    path('investigate/', InvestigationView.as_view(), name='investigate'),
    path('contact/', ContactView.as_view(), name='contact'),
    # Action Agent (docs/action-agent-scope.md F5). Approver token required on all of them.
    path('actions/pending/', PendingActionsView.as_view(), name='actions-pending'),
    path('actions/log/', ActionLogView.as_view(), name='actions-log'),
    path('actions/<str:proposal_id>/approve/', ApproveActionView.as_view(), name='actions-approve'),
    path('actions/<str:proposal_id>/edit/', EditActionView.as_view(), name='actions-edit'),
    path('actions/<str:proposal_id>/reject/', RejectActionView.as_view(), name='actions-reject'),
    path('actions/<str:proposal_id>/undo/', UndoActionView.as_view(), name='actions-undo'),
]

"""
Main URL configuration.
"""

from django.contrib import admin
from django.urls import path, include
from metric_pulse_web.views import HomeView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('dashboard_api.urls')),
    path('', HomeView.as_view(), name='home'),
]

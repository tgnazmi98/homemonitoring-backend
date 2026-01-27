from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'meters', views.MeterViewSet)
router.register(r'power-readings', views.PowerReadingViewSet)
router.register(r'energy-readings', views.EnergyReadingViewSet)

urlpatterns = [
    # Custom API endpoints (must come BEFORE router to avoid conflicts)
    path('health/', views.health_check, name='health_check'),
    path('api/summary/', views.meter_readings_summary, name='meter_summary'),
    path('api/ingest/', views.ingest_meter_data, name='ingest_meter_data'),
    path('api/historical/<str:meter_name>/', views.meter_historical_data, name='meter_historical_data'),
    path('api/timeseries/<str:meter_name>/', views.timeseries_data, name='timeseries_data'),
    path('api/power-quality/<str:meter_name>/', views.power_quality_data, name='power_quality_data'),
    path('api/energy-consumption/<str:meter_name>/', views.energy_consumption_data, name='energy_consumption_data'),
    path('api/realtime/<str:meter_name>/', views.realtime_data, name='realtime_data'),
    path('api/export/<str:meter_name>/', views.export_data, name='export_data'),
    # Router URLs (REST API for models)
    path('api/', include(router.urls)),
]
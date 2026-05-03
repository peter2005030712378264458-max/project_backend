from django.urls import path

from .dashboard_views import (
    DashboardDeviceDetailView,
    DashboardFiltersView,
    DashboardRoomLoadsView,
    DashboardSummaryView,
    DashboardTimeseriesView,
    DashboardTopDevicesView,
)


urlpatterns = [
    path("dashboard/filters/", DashboardFiltersView.as_view(), name="dashboard-filters"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("dashboard/timeseries/", DashboardTimeseriesView.as_view(), name="dashboard-timeseries"),
    path("dashboard/top-devices/", DashboardTopDevicesView.as_view(), name="dashboard-top-devices"),
    path("dashboard/room-loads/", DashboardRoomLoadsView.as_view(), name="dashboard-room-loads"),
    path("dashboard/devices/<str:data_name>/", DashboardDeviceDetailView.as_view(), name="dashboard-device-detail"),
]

from django.http import Http404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import dashboard_queries


class DashboardFiltersView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(dashboard_queries.get_filters())


class DashboardSummaryView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(dashboard_queries.get_summary(request))


class DashboardTimeseriesView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(dashboard_queries.get_timeseries(request))


class DashboardTopDevicesView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(dashboard_queries.get_top_devices(request))


class DashboardRoomLoadsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(dashboard_queries.get_room_loads(request))


class DashboardDeviceDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, data_name):
        detail = dashboard_queries.get_device_detail(request, data_name)
        if detail is None:
            raise Http404("Device not found")
        return Response(detail)

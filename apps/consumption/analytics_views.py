from __future__ import annotations

from datetime import date

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import dashboard_queries
from .analytics_client import request_period_comparison
from .dashboard_db import dashboard_connection


DATE_PARAMS = ("period1_from", "period1_to", "period2_from", "period2_to")


def _parse_date_param(request, name: str) -> date:
    value = request.query_params.get(name)
    if not value:
        raise ValidationError({"detail": f"Параметр {name} обязателен"})
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({"detail": f"Параметр {name} должен быть в формате YYYY-MM-DD"}) from exc


def _parse_alpha(request) -> float:
    raw_value = request.query_params.get("alpha", "0.05")
    try:
        alpha = float(raw_value)
    except ValueError as exc:
        raise ValidationError({"detail": "Параметр alpha должен быть числом"}) from exc

    if not 0 < alpha < 1:
        raise ValidationError({"detail": "Параметр alpha должен быть больше 0 и меньше 1"})
    return alpha


def _validate_periods(period1_from: date, period1_to: date, period2_from: date, period2_to: date) -> None:
    if period1_from > period1_to:
        raise ValidationError({"detail": "В первом периоде дата начала позже даты конца"})
    if period2_from > period2_to:
        raise ValidationError({"detail": "Во втором периоде дата начала позже даты конца"})

    non_overlapping = period1_to < period2_from or period2_to < period1_from
    if not non_overlapping:
        raise ValidationError({"detail": "Периоды не должны пересекаться"})


class PeriodComparisonView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        period1_from = _parse_date_param(request, "period1_from")
        period1_to = _parse_date_param(request, "period1_to")
        period2_from = _parse_date_param(request, "period2_from")
        period2_to = _parse_date_param(request, "period2_to")
        alpha = _parse_alpha(request)
        _validate_periods(period1_from, period1_to, period2_from, period2_to)

        with dashboard_connection(dashboard_queries._metadata_db_alias()) as connection:
            data_names = dashboard_queries._matching_data_names(connection, request)

        if data_names == []:
            return Response({"detail": "По выбранным фильтрам не найдено счетчиков"}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "period_1": {
                "date_from": period1_from.isoformat(),
                "date_to": period1_to.isoformat(),
            },
            "period_2": {
                "date_from": period2_from.isoformat(),
                "date_to": period2_to.isoformat(),
            },
            "alpha": alpha,
            "data_names": data_names,
            "metric": "active_power_w_avg",
        }

        return Response(request_period_comparison(payload))

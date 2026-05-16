from __future__ import annotations

import httpx
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError


class AnalyticsServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Аналитический сервис недоступен"
    default_code = "analytics_service_unavailable"


class AnalyticsServiceBadGateway(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Аналитический сервис вернул неожиданный ответ"
    default_code = "analytics_service_bad_gateway"


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "Ошибка аналитического сервиса"

    detail = data.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        first_error = detail[0]
        if isinstance(first_error, dict):
            return first_error.get("msg") or str(first_error)
        return str(first_error)
    return data.get("error") or "Ошибка аналитического сервиса"


def request_period_comparison(payload: dict) -> dict:
    endpoint = f"{settings.ANALYTICS_SERVICE_URL.rstrip('/')}/internal/analytics/period-comparison"
    headers = {}
    if settings.ANALYTICS_SERVICE_TOKEN:
        headers["X-Internal-Token"] = settings.ANALYTICS_SERVICE_TOKEN

    try:
        with httpx.Client(timeout=settings.ANALYTICS_SERVICE_TIMEOUT_SECONDS) as client:
            response = client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AnalyticsServiceUnavailable("Аналитический сервис не ответил вовремя") from exc
    except httpx.RequestError as exc:
        raise AnalyticsServiceUnavailable("Аналитический сервис недоступен") from exc

    if response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        raise ValidationError({"detail": _extract_error_detail(response)})
    if 400 <= response.status_code < 500:
        raise AnalyticsServiceBadGateway(_extract_error_detail(response))
    if response.status_code >= 500:
        raise AnalyticsServiceUnavailable(_extract_error_detail(response))

    try:
        return response.json()
    except ValueError as exc:
        raise AnalyticsServiceBadGateway("Аналитический сервис вернул не JSON") from exc

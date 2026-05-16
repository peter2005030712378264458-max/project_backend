from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from .analytics_client import AnalyticsServiceUnavailable


class DummyUser:
    is_active = True
    is_authenticated = True


class PeriodComparisonViewTests(SimpleTestCase):
    endpoint = "/api/consumption/analytics/period-comparison/"

    def setUp(self):
        self.client = APIClient()
        self.user = DummyUser()

    def authenticate(self):
        self.client.force_authenticate(user=self.user)

    def test_unauthenticated_request_returns_401(self):
        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, 401)

    def test_missing_dates_return_400(self):
        self.authenticate()

        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, 400)

    def test_intersecting_periods_return_400(self):
        self.authenticate()

        response = self.client.get(
            self.endpoint,
            {
                "period1_from": "2021-01-01",
                "period1_to": "2021-01-10",
                "period2_from": "2021-01-10",
                "period2_to": "2021-01-15",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_alpha_returns_400(self):
        self.authenticate()

        response = self.client.get(
            self.endpoint,
            {
                "period1_from": "2021-01-01",
                "period1_to": "2021-01-02",
                "period2_from": "2021-01-03",
                "period2_to": "2021-01-04",
                "alpha": "1.2",
            },
        )

        self.assertEqual(response.status_code, 400)

    @patch("apps.consumption.analytics_views.request_period_comparison")
    @patch("apps.consumption.analytics_views.dashboard_queries._matching_data_names")
    @patch("apps.consumption.analytics_views.dashboard_connection")
    def test_successful_request_calls_analytics_service(self, dashboard_connection, matching_data_names, request_period_comparison):
        self.authenticate()
        dashboard_connection.return_value.__enter__.return_value = object()
        matching_data_names.return_value = ["meter-1", "meter-2"]
        request_period_comparison.return_value = {
            "hypothesis": "H0",
            "alternative": "two_sided",
            "alpha": 0.05,
            "metric": "active_power_w_avg",
            "unit": "kW",
            "periods": [],
            "difference_mean_kw": None,
            "standard_error": None,
            "z_statistic": None,
            "z_critical": 1.96,
            "reject_null": None,
            "conclusion": "ok",
            "table_lookup": {},
        }

        response = self.client.get(
            self.endpoint,
            {
                "period1_from": "2021-01-01",
                "period1_to": "2021-01-02",
                "period2_from": "2021-01-03",
                "period2_to": "2021-01-04",
                "alpha": "0.05",
            },
        )

        self.assertEqual(response.status_code, 200)
        request_period_comparison.assert_called_once_with(
            {
                "period_1": {"date_from": "2021-01-01", "date_to": "2021-01-02"},
                "period_2": {"date_from": "2021-01-03", "date_to": "2021-01-04"},
                "alpha": 0.05,
                "data_names": ["meter-1", "meter-2"],
                "metric": "active_power_w_avg",
            }
        )

    @patch("apps.consumption.analytics_views.request_period_comparison")
    @patch("apps.consumption.analytics_views.dashboard_queries._matching_data_names")
    @patch("apps.consumption.analytics_views.dashboard_connection")
    def test_service_unavailable_returns_503(self, dashboard_connection, matching_data_names, request_period_comparison):
        self.authenticate()
        dashboard_connection.return_value.__enter__.return_value = object()
        matching_data_names.return_value = None
        request_period_comparison.side_effect = AnalyticsServiceUnavailable("Аналитический сервис недоступен")

        response = self.client.get(
            self.endpoint,
            {
                "period1_from": "2021-01-01",
                "period1_to": "2021-01-02",
                "period2_from": "2021-01-03",
                "period2_to": "2021-01-04",
            },
        )

        self.assertEqual(response.status_code, 503)

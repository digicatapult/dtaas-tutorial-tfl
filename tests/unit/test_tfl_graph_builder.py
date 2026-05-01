import importlib
from unittest.mock import MagicMock, patch

import pytest
import responses
from requests.exceptions import ConnectionError, HTTPError, Timeout

TFL_BASE_URL = "https://api.tfl.gov.uk"


def _import_graph_builder(mock_driver=None):
    if mock_driver is None:
        mock_driver = MagicMock()
    with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
        import agents.tfl_graph_builder as gb

        importlib.reload(gb)
        gb.driver = mock_driver
        gb.station_cache.clear()
    return gb


@pytest.mark.unit
class TestGetLines:
    @responses.activate
    def test_returns_parsed_json(self, tfl_lines_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/Mode/tube",
            json=tfl_lines_json,
            status=200,
        )
        gb = _import_graph_builder()
        result = gb.get_lines()
        assert len(result) == 2
        assert result[0]["id"] == "victoria"
        assert result[1]["id"] == "central"

    @responses.activate
    def test_raises_on_server_error(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/Mode/tube",
            status=503,
        )
        gb = _import_graph_builder()
        with pytest.raises(HTTPError):
            gb.get_lines()


@pytest.mark.unit
class TestGetStationsForLine:
    @responses.activate
    def test_returns_stations(self, tfl_victoria_stoppoints_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/StopPoints",
            json=tfl_victoria_stoppoints_json,
            status=200,
        )
        gb = _import_graph_builder()
        result = gb.get_stations_for_line("victoria")
        assert len(result) == 3

    @responses.activate
    def test_returns_empty_on_404(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/fake-line/StopPoints",
            status=404,
        )
        gb = _import_graph_builder()
        result = gb.get_stations_for_line("fake-line")
        assert result == []

    @responses.activate
    def test_returns_empty_on_429(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/StopPoints",
            status=429,
        )
        gb = _import_graph_builder()
        result = gb.get_stations_for_line("victoria")
        assert result == []

    @responses.activate
    def test_returns_empty_on_503(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/StopPoints",
            status=503,
        )
        gb = _import_graph_builder()
        result = gb.get_stations_for_line("victoria")
        assert result == []


@pytest.mark.unit
class TestFetchStation:
    @responses.activate
    def test_returns_station_data(self, tfl_station_greenpark_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/StopPoint/940GZZLUGPK",
            json=tfl_station_greenpark_json,
            status=200,
        )
        gb = _import_graph_builder()
        result = gb.fetch_station("940GZZLUGPK")
        assert result["commonName"] == "Green Park Underground Station"

    @responses.activate
    def test_caches_result(self, tfl_station_greenpark_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/StopPoint/940GZZLUGPK",
            json=tfl_station_greenpark_json,
            status=200,
        )
        gb = _import_graph_builder()
        gb.fetch_station("940GZZLUGPK")
        result = gb.fetch_station("940GZZLUGPK")
        assert result["commonName"] == "Green Park Underground Station"
        assert len(responses.calls) == 1

    @responses.activate
    def test_returns_none_on_404(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/StopPoint/FAKE",
            status=404,
        )
        gb = _import_graph_builder()
        result = gb.fetch_station("FAKE")
        assert result is None

    @responses.activate
    def test_returns_none_on_timeout(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/StopPoint/TIMEOUT",
            body=ConnectionError("Connection timed out"),
        )
        gb = _import_graph_builder()
        result = gb.fetch_station("TIMEOUT")
        assert result is None


@pytest.mark.unit
class TestGetRoutesForLine:
    @responses.activate
    def test_returns_both_directions(
        self, tfl_victoria_route_inbound_json, tfl_victoria_route_outbound_json
    ):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/inbound",
            json=tfl_victoria_route_inbound_json,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/outbound",
            json=tfl_victoria_route_outbound_json,
            status=200,
        )
        gb = _import_graph_builder()
        routes = gb.get_routes_for_line("victoria")
        assert len(routes) == 2

    @responses.activate
    def test_handles_404_inbound_gracefully(self, tfl_victoria_route_outbound_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/inbound",
            status=404,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/outbound",
            json=tfl_victoria_route_outbound_json,
            status=200,
        )
        gb = _import_graph_builder()
        routes = gb.get_routes_for_line("victoria")
        assert len(routes) == 1

    @responses.activate
    def test_handles_503_prints_warning(self, tfl_victoria_route_inbound_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/inbound",
            json=tfl_victoria_route_inbound_json,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/outbound",
            status=503,
        )
        gb = _import_graph_builder()
        routes = gb.get_routes_for_line("victoria")
        assert len(routes) == 1


@pytest.mark.unit
class TestCreateGraph:
    @responses.activate
    def test_creates_nodes_and_relationships(
        self,
        tfl_lines_json,
        tfl_victoria_stoppoints_json,
        tfl_victoria_route_inbound_json,
        tfl_victoria_route_outbound_json,
    ):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        lines_data = [tfl_lines_json[0]]
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/Mode/tube",
            json=lines_data,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/StopPoints",
            json=tfl_victoria_stoppoints_json,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/inbound",
            json=tfl_victoria_route_inbound_json,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/outbound",
            json=tfl_victoria_route_outbound_json,
            status=200,
        )

        gb = _import_graph_builder(mock_driver)
        gb.create_graph()

        cypher_calls = [call.args[0] for call in mock_session.run.call_args_list]
        cypher_text = " ".join(cypher_calls)

        assert "TransportOperator" in cypher_text
        assert "Line" in cypher_text
        assert "Station" in cypher_text
        assert "Route" in cypher_text
        assert mock_session.run.call_count >= 5

    @responses.activate
    def test_accessibility_features_creation(
        self,
        tfl_lines_json,
    ):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        lines_data = [tfl_lines_json[0]]
        stoppoints_data = [
            {
                "id": "940GZZLUGPK",
                "commonName": "Green Park",
                "lat": 51.5,
                "lon": -0.14,
                "additionalProperties": [
                    {"key": "AccessViaLift", "value": "Yes"},
                    {"key": "Toilet", "value": "No"},
                    {"key": "TaxiRankOutsideStation", "value": "Yes"},
                    {"key": "NonExistentFeature", "value": "Yes"},
                ],
            }
        ]

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/Mode/tube",
            json=lines_data,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/StopPoints",
            json=stoppoints_data,
            status=200,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/inbound",
            status=404,
        )
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Route/Sequence/outbound",
            status=404,
        )

        gb = _import_graph_builder(mock_driver)
        gb.create_graph()

        # Verify AccessibilityFeature nodes creation
        feature_names = []
        for call_obj in mock_session.run.call_args_list:
            call_text = call_obj.args[0]
            # Handle parameters from args (positional) or kwargs
            params = {}
            if len(call_obj.args) > 1:
                params = call_obj.args[1]
            elif "parameters" in call_obj.kwargs:
                params = call_obj.kwargs["parameters"]
            else:
                params = call_obj.kwargs

            if "AccessibilityFeature" in call_text:
                feature_names.append(params.get("feat"))

        # Assert at least some features were created (the logic depends on accessibility_features_of_interest)
        assert len(feature_names) > 0
        assert "AccessViaLift" in feature_names

        # Verify relationship creation
        has_feature_rel = any(
            "hasAccessibilityFeature" in call_obj.args[0]
            for call_obj in mock_session.run.call_args_list
        )
        assert has_feature_rel

    @responses.activate
    def test_malformed_json_raises(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/Mode/tube",
            body="not json at all",
            status=200,
        )
        gb = _import_graph_builder()
        with pytest.raises(Exception):
            gb.get_lines()

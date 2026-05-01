import importlib
from unittest.mock import MagicMock, patch, call

import pytest
import responses

TFL_BASE_URL = "https://api.tfl.gov.uk"


def _import_train_loader(mock_driver=None, mock_write_api=None):
    if mock_driver is None:
        mock_driver = MagicMock()
    if mock_write_api is None:
        mock_write_api = MagicMock()

    with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
        with patch("influxdb_client.InfluxDBClient") as mock_influx_cls:
            mock_client = MagicMock()
            mock_client.write_api.return_value = mock_write_api
            mock_influx_cls.return_value = mock_client

            import legacy.tfl_train_loader as loader

            importlib.reload(loader)
            loader.driver = mock_driver
            loader.write_api = mock_write_api

    return loader


@pytest.mark.unit
class TestFetchActiveTrains:
    @responses.activate
    def test_filters_nearest_prediction_per_vehicle(
        self, tfl_victoria_arrivals_json, mock_influx_write_api
    ):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=tfl_victoria_arrivals_json,
            status=200,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")

        vehicle_ids = [t["vehicleId"] for t in result]
        assert "101" in vehicle_ids
        assert "202" in vehicle_ids
        assert "303" in vehicle_ids

        train_101 = next(t for t in result if t["vehicleId"] == "101")
        assert train_101["timeToStation"] == 120

    @responses.activate
    def test_skips_trains_missing_direction(self, mock_influx_write_api):
        arrivals = [
            {
                "vehicleId": "999",
                "lineId": "victoria",
                "direction": None,
                "naptanId": "940GZZLUGPK",
                "destinationNaptanId": "940GZZLUBXN",
                "timeToStation": 60,
            }
        ]
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=arrivals,
            status=200,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")
        assert len(result) == 0

    @responses.activate
    def test_returns_empty_on_non_200(self, mock_influx_write_api):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=500,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")
        assert result == []

    @responses.activate
    def test_skips_trains_missing_naptan(self, mock_influx_write_api):
        arrivals = [
            {
                "vehicleId": "888",
                "lineId": "victoria",
                "direction": "inbound",
                "naptanId": None,
                "destinationNaptanId": "940GZZLUBXN",
                "timeToStation": 60,
            }
        ]
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=arrivals,
            status=200,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")
        assert len(result) == 0


@pytest.mark.unit
class TestWriteTrainsToInflux:
    def test_writes_correct_number_of_points(self, mock_influx_write_api):
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        trains = [
            {
                "vehicleId": "101",
                "timeToStation": 120,
                "direction": "inbound",
                "naptanId": "940GZZLUGPK",
                "destinationNaptanId": "940GZZLUBXN",
                "expectedArrival": "2025-01-15T12:05:00Z",
            },
            {
                "vehicleId": "202",
                "timeToStation": 60,
                "direction": "outbound",
                "naptanId": "940GZZLUVXL",
                "destinationNaptanId": "940GZZLUWWL",
                "expectedArrival": "2025-01-15T12:04:00Z",
            },
        ]
        loader.write_trains_to_influx(trains, "victoria")
        mock_influx_write_api.write.assert_called_once()
        written_points = mock_influx_write_api.write.call_args
        assert (
            len(
                written_points.kwargs.get("record", written_points[1].get("record", []))
            )
            == 2
        )

    def test_no_write_on_empty_trains(self, mock_influx_write_api):
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        loader.write_trains_to_influx([], "victoria")
        mock_influx_write_api.write.assert_not_called()


@pytest.mark.unit
class TestDeleteAllTrains:
    def test_runs_detach_delete(self, mock_neo4j_driver):
        mock_driver, mock_session, _ = mock_neo4j_driver
        loader = _import_train_loader(mock_driver=mock_driver)
        loader.delete_all_trains()
        cypher = mock_session.run.call_args[0][0]
        assert "DETACH DELETE" in cypher


@pytest.mark.unit
class TestCreateTrainAndLinkRoute:
    def test_merges_train_and_links_route(self, mock_neo4j_driver):
        _, _, mock_tx = mock_neo4j_driver
        mock_driver = mock_neo4j_driver[0]
        loader = _import_train_loader(mock_driver=mock_driver)

        train = {
            "vehicleId": "101",
            "lineId": "victoria",
            "direction": "inbound",
            "timestamp": "2025-01-15T12:03:00Z",
            "stationName": "Green Park",
            "naptanId": "940GZZLUGPK",
            "timeToStation": 120,
            "destinationName": "Brixton",
            "destinationNaptanId": "940GZZLUBXN",
            "expectedArrival": "2025-01-15T12:05:00Z",
        }
        route = {"routeId": "victoria-route-0"}

        loader.create_train_and_link_route(mock_tx, train, route)

        assert mock_tx.run.call_count == 2
        first_cypher = mock_tx.run.call_args_list[0][0][0]
        assert "MERGE (t:Train" in first_cypher
        second_cypher = mock_tx.run.call_args_list[1][0][0]
        assert "servesRoute" in second_cypher


@pytest.mark.unit
class TestFindMatchingRoutes:
    def test_executes_correct_cypher(self, mock_neo4j_driver):
        mock_driver, mock_session, _ = mock_neo4j_driver
        mock_session.run.return_value = []
        loader = _import_train_loader(mock_driver=mock_driver)

        loader.find_matching_routes(
            mock_driver, "victoria", "inbound", "940GZZLUBXN", "940GZZLUGPK"
        )

        cypher = mock_session.run.call_args[0][0]
        assert "Route" in cypher
        assert "stationSequence" in cypher


@pytest.mark.unit
class TestLoadTrainsForLine:
    @responses.activate
    def test_single_route_match_creates_train(
        self, mock_neo4j_driver, mock_influx_write_api
    ):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver

        mock_route = MagicMock()
        mock_route.__getitem__ = lambda self, key: {"routeId": "victoria-route-0"}[key]
        mock_session.run.return_value = [{"r": mock_route}]

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=[
                {
                    "vehicleId": "101",
                    "lineId": "victoria",
                    "direction": "inbound",
                    "naptanId": "940GZZLUGPK",
                    "destinationNaptanId": "940GZZLUBXN",
                    "timeToStation": 120,
                    "expectedArrival": "2025-01-15T12:05:00Z",
                    "timestamp": "2025-01-15T12:03:00Z",
                    "stationName": "Green Park",
                    "destinationName": "Brixton",
                }
            ],
            status=200,
        )

        loader = _import_train_loader(
            mock_driver=mock_driver, mock_write_api=mock_influx_write_api
        )
        loader.load_trains_for_line("victoria")

        assert mock_tx.run.call_count >= 2

    @responses.activate
    def test_no_active_trains_returns_early(
        self, mock_neo4j_driver, mock_influx_write_api
    ):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=500,
        )

        loader = _import_train_loader(
            mock_driver=mock_driver, mock_write_api=mock_influx_write_api
        )
        loader.load_trains_for_line("victoria")

        mock_tx.run.assert_not_called()

    @responses.activate
    def test_multiple_route_matches_skips_train(
        self, mock_neo4j_driver, mock_influx_write_api
    ):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver

        mock_route_1 = MagicMock()
        mock_route_2 = MagicMock()
        mock_session.run.return_value = [{"r": mock_route_1}, {"r": mock_route_2}]

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=[
                {
                    "vehicleId": "101",
                    "lineId": "victoria",
                    "direction": "inbound",
                    "naptanId": "940GZZLUGPK",
                    "destinationNaptanId": "940GZZLUBXN",
                    "timeToStation": 120,
                }
            ],
            status=200,
        )

        loader = _import_train_loader(
            mock_driver=mock_driver, mock_write_api=mock_influx_write_api
        )
        loader.load_trains_for_line("victoria")

        mock_tx.run.assert_not_called()

    @responses.activate
    def test_no_route_match_skips_train(self, mock_neo4j_driver, mock_influx_write_api):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver
        mock_session.run.return_value = []

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=[
                {
                    "vehicleId": "101",
                    "lineId": "victoria",
                    "direction": "inbound",
                    "naptanId": "940GZZLUGPK",
                    "destinationNaptanId": "940GZZLUBXN",
                    "timeToStation": 120,
                }
            ],
            status=200,
        )

        loader = _import_train_loader(
            mock_driver=mock_driver, mock_write_api=mock_influx_write_api
        )
        loader.load_trains_for_line("victoria")

        mock_tx.run.assert_not_called()


@pytest.mark.unit
class TestLoadAllLines:
    @responses.activate
    def test_deletes_and_loads_all_lines(
        self, mock_neo4j_driver, mock_influx_write_api
    ):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver

        for line_id in [
            "bakerloo",
            "central",
            "circle",
            "district",
            "hammersmith-city",
            "jubilee",
            "metropolitan",
            "northern",
            "piccadilly",
            "victoria",
            "waterloo-city",
        ]:
            responses.add(
                responses.GET,
                f"{TFL_BASE_URL}/Line/{line_id}/Arrivals",
                json=[],
                status=200,
            )

        loader = _import_train_loader(
            mock_driver=mock_driver, mock_write_api=mock_influx_write_api
        )
        loader.load_all_lines()

        delete_calls = [
            c for c in mock_session.run.call_args_list if "DETACH DELETE" in str(c)
        ]
        assert len(delete_calls) >= 1


@pytest.mark.unit
class TestFetchActiveTrainsErrorPaths:
    @responses.activate
    def test_returns_empty_on_429_rate_limit(self, mock_influx_write_api):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=429,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")
        assert result == []

    @responses.activate
    def test_returns_empty_on_503_service_unavailable(self, mock_influx_write_api):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=503,
        )
        loader = _import_train_loader(mock_write_api=mock_influx_write_api)
        result = loader.fetch_active_trains("victoria")
        assert result == []

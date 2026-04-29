import importlib
import json
from unittest.mock import MagicMock, patch

import pytest
import responses

TFL_BASE_URL = "https://api.tfl.gov.uk"


def _import_adapter(mock_driver=None):
    if mock_driver is None:
        mock_driver = MagicMock()
    with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
        import agents.neo4j_adapter as adapter

        importlib.reload(adapter)
        adapter.driver = mock_driver
    return adapter


@pytest.mark.unit
class TestFetchActiveTrains:
    @responses.activate
    def test_filters_nearest_prediction_per_vehicle(self, tfl_victoria_arrivals_json):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=tfl_victoria_arrivals_json,
            status=200,
        )
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")

        vehicle_ids = [t["vehicleId"] for t in result]
        assert "101" in vehicle_ids
        assert "202" in vehicle_ids

        train_101 = next(t for t in result if t["vehicleId"] == "101")
        assert train_101["timeToStation"] == 120

    @responses.activate
    def test_returns_empty_on_api_error(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=500,
        )
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")
        assert result == []

    @responses.activate
    def test_skips_trains_missing_fields(self):
        arrivals = [
            {
                "vehicleId": "777",
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
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")
        assert len(result) == 0


@pytest.mark.unit
class TestOnMessage:
    @responses.activate
    def test_processes_valid_mqtt_payload(self, tfl_victoria_arrivals_json):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_tx = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_tx.__enter__ = MagicMock(return_value=mock_tx)
        mock_tx.__exit__ = MagicMock(return_value=False)
        mock_session.begin_transaction.return_value = mock_tx
        mock_driver.session.return_value = mock_session

        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            json=tfl_victoria_arrivals_json,
            status=200,
        )
        mock_session.run.return_value = []

        adapter = _import_adapter(mock_driver)

        payload = json.dumps(
            [{"lineId": "victoria", "vehicleId": "101", "direction": "inbound"}]
        )
        mock_msg = MagicMock()
        mock_msg.topic = "tfl/victoria"
        mock_msg.payload = payload.encode()

        adapter.on_message(None, None, mock_msg)

        delete_calls = [
            c for c in mock_session.run.call_args_list if "DETACH DELETE" in str(c)
        ]
        assert len(delete_calls) >= 1

    def test_handles_empty_payload_gracefully(self):
        adapter = _import_adapter()
        mock_msg = MagicMock()
        mock_msg.topic = "tfl/test"
        mock_msg.payload = b"[]"

        adapter.on_message(None, None, mock_msg)

    def test_handles_missing_line_id_gracefully(self):
        adapter = _import_adapter()
        mock_msg = MagicMock()
        mock_msg.topic = "tfl/test"
        mock_msg.payload = json.dumps([{"vehicleId": "101"}]).encode()

        try:
            adapter.on_message(None, None, mock_msg)
        except KeyError:
            pass


@pytest.mark.unit
class TestDeleteTrains:
    def test_runs_detach_delete_for_line(self, mock_neo4j_driver):
        mock_driver, mock_session, _ = mock_neo4j_driver
        adapter = _import_adapter(mock_driver)
        adapter.delete_trains("victoria")
        cypher = mock_session.run.call_args[0][0]
        assert "DETACH DELETE" in cypher
        assert "lineId" in str(mock_session.run.call_args)


@pytest.mark.unit
class TestLoadTrainsForLine:
    def test_skips_trains_with_missing_data(self, mock_neo4j_driver):
        mock_driver, mock_session, mock_tx = mock_neo4j_driver
        adapter = _import_adapter(mock_driver)

        trains = [
            {
                "vehicleId": "999",
                "direction": None,
                "destinationNaptanId": "940GZZLUBXN",
                "naptanId": "940GZZLUGPK",
            }
        ]
        adapter.load_trains_for_line(trains, "victoria")
        mock_tx.run.assert_not_called()


@pytest.mark.unit
class TestMqttSetup:
    def test_main_configures_mqtt_client(self):
        adapter = _import_adapter()

        with patch("paho.mqtt.client.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance

            mock_instance.loop_forever.side_effect = KeyboardInterrupt

            try:
                adapter.main()
            except KeyboardInterrupt:
                pass

            MockClient.assert_called_once_with(
                transport="websockets", client_id="neo4j-adapter"
            )
            mock_instance.tls_set.assert_called_once()
            mock_instance.connect.assert_called_once()


@pytest.mark.unit
class TestOnConnect:
    def test_subscribes_to_mqtt_topic(self):
        adapter = _import_adapter()
        mock_client = MagicMock()
        adapter.on_connect(mock_client, None, None, 0)
        mock_client.subscribe.assert_called_once()


@pytest.mark.unit
class TestFindMatchingRoutes:
    def test_executes_route_query(self, mock_neo4j_driver):
        mock_driver, mock_session, _ = mock_neo4j_driver
        mock_session.run.return_value = []
        adapter = _import_adapter(mock_driver)

        result = adapter.find_matching_routes(
            mock_driver, "victoria", "inbound", "940GZZLUBXN", "940GZZLUGPK"
        )

        assert result == []
        cypher = mock_session.run.call_args[0][0]
        assert "Route" in cypher
        assert "stationSequence" in cypher

    def test_returns_matched_routes(self, mock_neo4j_driver):
        mock_driver, mock_session, _ = mock_neo4j_driver
        mock_route = MagicMock()
        mock_session.run.return_value = [{"r": mock_route}]
        adapter = _import_adapter(mock_driver)

        result = adapter.find_matching_routes(
            mock_driver, "victoria", "inbound", "940GZZLUBXN", "940GZZLUGPK"
        )

        assert len(result) == 1
        assert result[0] is mock_route


@pytest.mark.unit
class TestCreateTrainAndLinkRoute:
    def test_merges_train_and_links_route(self, mock_neo4j_driver):
        _, _, mock_tx = mock_neo4j_driver
        mock_driver = mock_neo4j_driver[0]
        adapter = _import_adapter(mock_driver)

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

        adapter.create_train_and_link_route(mock_tx, train, route)

        assert mock_tx.run.call_count == 2
        first_cypher = mock_tx.run.call_args_list[0][0][0]
        assert "MERGE (t:Train" in first_cypher
        second_cypher = mock_tx.run.call_args_list[1][0][0]
        assert "servesRoute" in second_cypher


@pytest.mark.unit
class TestFetchActiveTrainsErrorPaths:
    @responses.activate
    def test_returns_empty_on_429_rate_limit(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=429,
        )
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")
        assert result == []

    @responses.activate
    def test_returns_empty_on_503_service_unavailable(self):
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            status=503,
        )
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")
        assert result == []

    @responses.activate
    def test_handles_connection_error_gracefully(self):
        from requests.exceptions import ConnectionError
        responses.add(
            responses.GET,
            f"{TFL_BASE_URL}/Line/victoria/Arrivals",
            body=ConnectionError("Connection failed"),
        )
        adapter = _import_adapter()
        result = adapter.fetch_active_trains([], "victoria")
        assert result == []

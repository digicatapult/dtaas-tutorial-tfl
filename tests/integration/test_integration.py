import importlib
from unittest.mock import patch

import pytest

from tests.integration.conftest import (
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_PASSWORD,
)


@pytest.fixture()
def graph_builder(neo4j_driver, wiremock_url, monkeypatch):
    monkeypatch.setenv("NEO4J_URI", NEO4J_URI)
    monkeypatch.setenv("NEO4J_USER", NEO4J_USER)
    monkeypatch.setenv("NEO4J_PASSWORD", NEO4J_PASSWORD)

    import agents.tfl_graph_builder as gb

    importlib.reload(gb)
    gb.TFL_BASE_URL = wiremock_url
    gb.LINES_URL = f"{wiremock_url}/Line/Mode/tube"
    gb.driver = neo4j_driver
    gb.station_cache.clear()

    return gb


@pytest.mark.integration
class TestNeo4jGraphCreation:
    def test_create_graph_writes_nodes(self, neo4j_driver, graph_builder):
        graph_builder.create_graph()

        with neo4j_driver.session() as session:
            result = session.run(
                "MATCH (n) RETURN labels(n) AS labels, count(n) AS cnt"
            )
            counts = {r["labels"][0]: r["cnt"] for r in result}

        assert "TransportOperator" in counts
        assert "Line" in counts
        assert "Station" in counts
        assert counts["Station"] >= 1

    def test_station_properties_correct(self, neo4j_driver, graph_builder):
        graph_builder.create_graph()

        with neo4j_driver.session() as session:
            result = session.run(
                "MATCH (s:Station {stationId: '940GZZLUGPK'}) "
                "RETURN s.name AS name, s.latitude AS lat, s.longitude AS lon"
            )
            record = result.single()

        assert record is not None
        assert record["name"] == "Green Park Underground Station"
        assert abs(record["lat"] - 51.506947) < 0.001
        assert abs(record["lon"] - (-0.142787)) < 0.001

    def test_lines_from_both_tube_lines(self, neo4j_driver, graph_builder):
        graph_builder.create_graph()

        with neo4j_driver.session() as session:
            result = session.run(
                "MATCH (l:Line) RETURN l.lineId AS lineId ORDER BY l.lineId"
            )
            line_ids = [r["lineId"] for r in result]

        assert "victoria" in line_ids
        assert "central" in line_ids

    def test_routes_have_station_sequences(self, neo4j_driver, graph_builder):
        graph_builder.create_graph()

        with neo4j_driver.session() as session:
            result = session.run("MATCH (r:Route) RETURN r.stationSequence AS seq")
            sequences = [r["seq"] for r in result]

        assert len(sequences) >= 1
        assert all(len(seq) >= 2 for seq in sequences)

    def test_accessibility_features_created(self, neo4j_driver, graph_builder):
        graph_builder.create_graph()

        with neo4j_driver.session() as session:
            result = session.run(
                "MATCH (af:AccessibilityFeature) RETURN af.name AS name"
            )
            features = [r["name"] for r in result]

        assert len(features) >= 1


@pytest.mark.integration
class TestInfluxDBWriteRead:
    def test_write_and_query_train_points(self, influx_client):
        from influxdb_client import Point
        from influxdb_client.client.write_api import SYNCHRONOUS
        from datetime import datetime, UTC

        write_api = influx_client.write_api(write_options=SYNCHRONOUS)

        point = (
            Point("tfl_trains")
            .tag("lineId", "victoria")
            .tag("vehicleId", "test-101")
            .field("timeToStation", 120)
            .time(datetime.now(UTC))
        )
        write_api.write(bucket="TFL", record=[point])

        query_api = influx_client.query_api()
        query = (
            'from(bucket: "TFL") '
            "|> range(start: -1h) "
            '|> filter(fn: (r) => r._measurement == "tfl_trains") '
            '|> filter(fn: (r) => r.vehicleId == "test-101")'
        )
        tables = query_api.query(query)
        records = [r for table in tables for r in table.records]
        assert len(records) >= 1
        assert records[0].get_value() == 120


@pytest.mark.integration
class TestFastAPIWebSocket:
    def test_websocket_returns_json_with_stations_and_trains(
        self, neo4j_driver, graph_builder, monkeypatch
    ):
        graph_builder.create_graph()

        with patch("neo4j.GraphDatabase.driver", return_value=neo4j_driver):
            with patch("influxdb_client.InfluxDBClient"):
                import visualisation.main as vis

                importlib.reload(vis)
                vis.neo_driver = neo4j_driver

        import json
        from starlette.testclient import TestClient

        client = TestClient(vis.app)
        with client.websocket_connect("/ws/trains") as ws:
            data = ws.receive_text()
            payload = json.loads(data)
            assert "stations" in payload
            assert "trains" in payload
            assert isinstance(payload["stations"], list)

import asyncio
import importlib
import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_mock_neo_driver():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_driver.session.return_value = mock_session
    mock_driver.close = MagicMock()
    return mock_driver, mock_session


def _make_mock_influx_client():
    mock_client = MagicMock()
    mock_query_api = MagicMock()
    mock_client.query_api.return_value = mock_query_api
    mock_client.close = MagicMock()
    return mock_client, mock_query_api


def _import_app(mock_neo_driver, mock_influx_client):
    with patch("neo4j.GraphDatabase.driver", return_value=mock_neo_driver):
        with patch("influxdb_client.InfluxDBClient", return_value=mock_influx_client):
            import visualisation.main as vis_main

            importlib.reload(vis_main)
            vis_main.neo_driver = mock_neo_driver
            vis_main.influx_client = mock_influx_client
            vis_main.query_api = mock_influx_client.query_api()
    return vis_main


@pytest.mark.unit
class TestRootEndpoint:
    @pytest.mark.asyncio
    async def test_get_root_returns_html(self):
        mock_neo, _ = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()
        vis = _import_app(mock_neo, mock_influx)

        transport = ASGITransport(app=vis.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert (
                "Leaflet" in resp.text
                or "<!DOCTYPE" in resp.text.upper()
                or "<html" in resp.text.lower()
            )


@pytest.mark.unit
class TestWebSocketEndpoint:
    @pytest.mark.asyncio
    async def test_ws_trains_sends_json_payload(self):
        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()

        station_records = [
            {
                "id": "940GZZLUGPK",
                "name": "Green Park",
                "lat": 51.506947,
                "lon": -0.142787,
            }
        ]
        train_records = [
            {
                "trainId": "101",
                "lat": 51.506947,
                "lon": -0.142787,
                "lineId": "victoria",
                "lineName": "Victoria",
                "nextStationId": "940GZZLUGPK",
            }
        ]

        call_count = 0

        def mock_run(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if "Station" in query and "Train" not in query:
                return [
                    MagicMock(
                        __getitem__=lambda self, key: station_records[0][key],
                        data=lambda: station_records[0],
                    )
                ]
            else:
                record = MagicMock()
                record.__getitem__ = lambda self, key: {
                    "trainId": "101",
                    "nextStationId": "940GZZLUGPK",
                    "lat": 51.506947,
                    "lon": -0.142787,
                    "lineId": "victoria",
                    "lineName": "Victoria",
                }[key]
                return [record]

        mock_session.run.side_effect = mock_run

        vis = _import_app(mock_neo, mock_influx)

        from starlette.testclient import TestClient

        client = TestClient(vis.app)
        with client.websocket_connect("/ws/trains") as ws:
            data = ws.receive_text()
            payload = json.loads(data)
            assert "stations" in payload
            assert "trains" in payload
            assert len(payload["stations"]) == 1
            assert len(payload["trains"]) == 1


@pytest.mark.unit
class TestFetchStations:
    @pytest.mark.asyncio
    async def test_returns_stations_from_neo4j(self):
        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()

        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            "id": "940GZZLUGPK",
            "name": "Green Park",
            "lat": 51.506947,
            "lon": -0.142787,
        }[key]
        mock_session.run.return_value = [mock_record]

        vis = _import_app(mock_neo, mock_influx)
        result = await vis.fetch_stations()
        assert len(result) == 1
        assert result[0]["name"] == "Green Park"

    @pytest.mark.asyncio
    async def test_returns_empty_on_neo4j_error(self):
        from neo4j import exceptions as neo4j_exceptions

        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()
        mock_session.run.side_effect = neo4j_exceptions.Neo4jError("test error")

        vis = _import_app(mock_neo, mock_influx)
        result = await vis.fetch_stations()
        assert result == []


@pytest.mark.unit
class TestFetchLiveTrains:
    @pytest.mark.asyncio
    async def test_returns_trains_from_neo4j(self):
        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()

        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            "trainId": "101",
            "nextStationId": "940GZZLUGPK",
            "lat": 51.506947,
            "lon": -0.142787,
            "lineId": "victoria",
            "lineName": "Victoria",
        }[key]
        mock_session.run.return_value = [mock_record]

        vis = _import_app(mock_neo, mock_influx)
        result = await vis.fetch_live_trains()
        assert len(result) == 1
        assert result[0]["trainId"] == "101"
        assert result[0]["lineId"] == "victoria"
        assert result[0]["line"] == "Victoria"
        assert result[0]["lat"] == 51.506947
        assert "eta" in result[0]

    @pytest.mark.asyncio
    async def test_handles_null_line_fields(self):
        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()

        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: {
            "trainId": "999",
            "nextStationId": "940GZZLUGPK",
            "lat": 51.506947,
            "lon": -0.142787,
            "lineId": None,
            "lineName": None,
        }[key]
        mock_session.run.return_value = [mock_record]

        vis = _import_app(mock_neo, mock_influx)
        result = await vis.fetch_live_trains()
        assert len(result) == 1
        assert result[0]["lineId"] == "unknown"
        assert result[0]["line"] == "Unknown"

    @pytest.mark.asyncio
    async def test_returns_empty_on_neo4j_error(self):
        from neo4j import exceptions as neo4j_exceptions

        mock_neo, mock_session = _make_mock_neo_driver()
        mock_influx, _ = _make_mock_influx_client()
        mock_session.run.side_effect = neo4j_exceptions.Neo4jError("test error")

        vis = _import_app(mock_neo, mock_influx)
        result = await vis.fetch_live_trains()
        assert result == []

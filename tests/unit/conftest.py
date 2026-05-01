from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("INFLUX_URL", raising=False)
    monkeypatch.delenv("INFLUX_TOKEN", raising=False)
    monkeypatch.delenv("INFLUX_ORG", raising=False)
    monkeypatch.delenv("INFLUX_BUCKET", raising=False)
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)
    monkeypatch.delenv("MQTT_TOPIC", raising=False)
    monkeypatch.delenv("MQTT_USER", raising=False)
    monkeypatch.delenv("MQTT_PASS", raising=False)


@pytest.fixture
def mock_neo4j_driver():
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_tx = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_tx.__enter__ = MagicMock(return_value=mock_tx)
    mock_tx.__exit__ = MagicMock(return_value=False)
    mock_session.begin_transaction.return_value = mock_tx
    mock_driver.session.return_value = mock_session
    return mock_driver, mock_session, mock_tx


@pytest.fixture
def mock_influx_write_api():
    return MagicMock()

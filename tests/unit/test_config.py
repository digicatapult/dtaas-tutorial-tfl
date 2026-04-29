import importlib
from unittest.mock import patch

import pytest


def _reload_config():
    with patch("dotenv.load_dotenv"):
        import config

        importlib.reload(config)
    return config


@pytest.mark.unit
class TestConfigDefaults:
    def test_neo4j_uri_default(self, monkeypatch):
        monkeypatch.delenv("NEO4J_URI", raising=False)
        config = _reload_config()
        assert config.NEO4J_URI == "bolt://localhost:7687"

    def test_neo4j_user_default(self, monkeypatch):
        monkeypatch.delenv("NEO4J_USER", raising=False)
        config = _reload_config()
        assert config.NEO4J_USER == "neo4j"

    def test_neo4j_password_default_empty(self, monkeypatch):
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        config = _reload_config()
        assert config.NEO4J_PASSWORD == ""

    def test_influx_url_default(self, monkeypatch):
        monkeypatch.delenv("INFLUX_URL", raising=False)
        config = _reload_config()
        assert config.INFLUX_URL == "http://localhost:8086"

    def test_influx_org_default(self, monkeypatch):
        monkeypatch.delenv("INFLUX_ORG", raising=False)
        config = _reload_config()
        assert config.INFLUX_ORG == "UKDTC"

    def test_influx_bucket_default(self, monkeypatch):
        monkeypatch.delenv("INFLUX_BUCKET", raising=False)
        config = _reload_config()
        assert config.INFLUX_BUCKET == "TFL"

    def test_mqtt_port_default(self, monkeypatch):
        monkeypatch.delenv("MQTT_PORT", raising=False)
        config = _reload_config()
        assert config.MQTT_PORT == 9443

    def test_mqtt_topic_default(self, monkeypatch):
        monkeypatch.delenv("MQTT_TOPIC", raising=False)
        config = _reload_config()
        assert config.MQTT_TOPIC == "tfl/#"


@pytest.mark.unit
class TestConfigEnvOverrides:
    def test_neo4j_uri_from_env(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://test:7687")
        config = _reload_config()
        assert config.NEO4J_URI == "bolt://test:7687"

    def test_neo4j_password_from_env(self, monkeypatch):
        monkeypatch.setenv("NEO4J_PASSWORD", "secret")
        config = _reload_config()
        assert config.NEO4J_PASSWORD == "secret"

    def test_influx_token_from_env(self, monkeypatch):
        monkeypatch.setenv("INFLUX_TOKEN", "my-token-123")
        config = _reload_config()
        assert config.INFLUX_TOKEN == "my-token-123"

    def test_mqtt_port_from_env(self, monkeypatch):
        monkeypatch.setenv("MQTT_PORT", "1883")
        config = _reload_config()
        assert config.MQTT_PORT == 1883

    def test_mqtt_host_derived_from_root_host(self, monkeypatch):
        monkeypatch.setenv("UKDTC_ROOT_HOST", "custom.host.io")
        monkeypatch.delenv("MQTT_HOST", raising=False)
        config = _reload_config()
        assert config.MQTT_HOST == "mosquitto.custom.host.io"

    def test_mqtt_host_explicit_override(self, monkeypatch):
        monkeypatch.setenv("MQTT_HOST", "my-broker.local")
        config = _reload_config()
        assert config.MQTT_HOST == "my-broker.local"

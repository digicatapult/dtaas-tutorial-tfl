import os
import time

import pytest
from neo4j import GraphDatabase
from influxdb_client import InfluxDBClient

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "testpassword")

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "test-token-123")
INFLUX_ORG = os.getenv("INFLUX_ORG", "UKDTC")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "TFL")

WIREMOCK_URL = os.getenv("WIREMOCK_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    _wait_for_neo4j(driver)
    yield driver
    driver.close()


def _wait_for_neo4j(driver, retries=30, delay=2):
    for _ in range(retries):
        try:
            driver.verify_connectivity()
            return
        except Exception:
            time.sleep(delay)
    raise RuntimeError("Neo4j did not become available")


@pytest.fixture(scope="session")
def influx_client():
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    yield client
    client.close()


@pytest.fixture(scope="session")
def wiremock_url():
    return WIREMOCK_URL


@pytest.fixture(autouse=True)
def _clean_neo4j(neo4j_driver):
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

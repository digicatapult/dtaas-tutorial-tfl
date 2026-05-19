import importlib
import os
import threading
import time

import pytest
import uvicorn
from neo4j import GraphDatabase

WIREMOCK_URL = os.getenv("WIREMOCK_URL", "http://localhost:8080")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "testpassword")
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "test-token-123")
INFLUX_ORG = os.getenv("INFLUX_ORG", "UKDTC")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "TFL")

FASTAPI_HOST = "127.0.0.1"
FASTAPI_PORT = 8111


@pytest.fixture(scope="module")
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    for _ in range(30):
        try:
            driver.verify_connectivity()
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("Neo4j did not become available")
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def seeded_graph(neo4j_driver):
    """Build static graph from WireMock, then seed a train node for visualisation."""
    import agents.tfl_graph_builder as gb

    importlib.reload(gb)
    gb.TFL_BASE_URL = WIREMOCK_URL
    gb.LINES_URL = f"{WIREMOCK_URL}/Line/Mode/tube"
    gb.driver = neo4j_driver
    gb.station_cache.clear()
    gb.create_graph()

    with neo4j_driver.session() as session:
        session.run("""
            MATCH (st:Station {stationId: '940GZZLUGPK'})
            MERGE (t:Train {vehicleId: 'e2e-train-001'})
            SET t.lineId = 'victoria',
                t.direction = 'inbound',
                t.nextStationId = st.stationId,
                t.nextStationName = st.name,
                t.secondsToNextStop = 60,
                t.expectedArrival = '2025-01-15T12:05:00Z'
            WITH t
            MATCH (r:Route {routeId: 'victoria-route-0'})
            MERGE (t)-[:servesRoute]->(r)
            """)

    yield neo4j_driver

    try:
        with neo4j_driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
    except Exception:
        pass  # Driver may already be closed by FastAPI lifespan shutdown


@pytest.fixture(scope="module")
def fastapi_server(seeded_graph):
    """Start FastAPI in a background thread pointed at the seeded Neo4j."""
    os.environ["NEO4J_URI"] = NEO4J_URI
    os.environ["NEO4J_USER"] = NEO4J_USER
    os.environ["NEO4J_PASSWORD"] = NEO4J_PASSWORD
    os.environ["INFLUX_URL"] = INFLUX_URL
    os.environ["INFLUX_TOKEN"] = INFLUX_TOKEN
    os.environ["INFLUX_ORG"] = INFLUX_ORG
    os.environ["INFLUX_BUCKET"] = INFLUX_BUCKET

    import visualisation.main as vis

    importlib.reload(vis)
    vis.neo_driver = seeded_graph

    config = uvicorn.Config(
        vis.app,
        host=FASTAPI_HOST,
        port=FASTAPI_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import httpx

    for _ in range(30):
        try:
            resp = httpx.get(f"http://{FASTAPI_HOST}:{FASTAPI_PORT}/")
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("FastAPI server did not start")

    yield f"http://{FASTAPI_HOST}:{FASTAPI_PORT}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.e2e
class TestFullPipeline:

    def test_map_page_loads(self, fastapi_server, page):
        """Given the server is running, the root page shows the Leaflet map."""
        page.goto(fastapi_server)
        page.wait_for_selector("#map", timeout=10000)
        assert page.title() == "London Underground Live Map"
        assert page.locator("#map").is_visible()

    def test_station_markers_appear(self, fastapi_server, page):
        """Given graph data exists, station circleMarkers render on the map."""
        page.goto(fastapi_server)
        page.wait_for_selector("#map", timeout=10000)

        page.locator(".leaflet-interactive").first.wait_for(timeout=15000)

        count = page.locator(".leaflet-interactive").count()
        assert count >= 3, f"Expected >=3 markers on map, got {count}"

    def test_train_marker_appears(self, fastapi_server, page):
        """Given a seeded train, total markers include stations + at least 1 train."""
        page.goto(fastapi_server)
        page.wait_for_selector("#map", timeout=10000)

        page.locator(".leaflet-interactive").first.wait_for(timeout=15000)

        count = page.locator(".leaflet-interactive").count()
        assert count >= 4, f"Expected >=4 markers (stations+trains), got {count}"

    def test_popup_opens_on_marker_click(self, fastapi_server, page):
        """Given markers exist, clicking one opens a non-empty popup."""
        page.goto(fastapi_server)
        page.wait_for_selector("#map", timeout=10000)
        page.locator(".leaflet-interactive").first.wait_for(timeout=15000)

        page.locator(".leaflet-interactive").first.click()

        popup = page.locator(".leaflet-popup-content")
        popup.wait_for(timeout=5000)
        assert len(popup.inner_text()) > 0, "Popup was empty"

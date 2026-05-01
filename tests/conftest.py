import json
from pathlib import Path

import pytest

WIREMOCK_DIR = Path(__file__).parent / "wiremock" / "__files"


@pytest.fixture
def wiremock_dir():
    return WIREMOCK_DIR


@pytest.fixture
def tfl_lines_json():
    return json.loads((WIREMOCK_DIR / "lines.json").read_text())


@pytest.fixture
def tfl_victoria_stoppoints_json():
    return json.loads((WIREMOCK_DIR / "victoria_stoppoints.json").read_text())


@pytest.fixture
def tfl_victoria_route_inbound_json():
    return json.loads((WIREMOCK_DIR / "victoria_route_inbound.json").read_text())


@pytest.fixture
def tfl_victoria_route_outbound_json():
    return json.loads((WIREMOCK_DIR / "victoria_route_outbound.json").read_text())


@pytest.fixture
def tfl_victoria_arrivals_json():
    return json.loads((WIREMOCK_DIR / "victoria_arrivals.json").read_text())


@pytest.fixture
def tfl_station_greenpark_json():
    return json.loads((WIREMOCK_DIR / "station_940GZZLUGPK.json").read_text())

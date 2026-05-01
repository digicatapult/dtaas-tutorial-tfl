# dtaas-tutorial-tfl

A Digital Twin as a Service (DTaaS) tutorial using the Transport for London API. This project builds a live digital twin of the London Underground by pulling real-time train data from the TfL Unified API, storing the network topology and train positions in Neo4j, recording time-series telemetry in InfluxDB, and visualising the result on a Leaflet.js map served via FastAPI.

The ontology is defined in DTDL V3 (`dtdl/LondonUnderground.json`) with six interfaces: **Station**, **Route**, **Train**, **Line**, **TransportOperator**, and **AccessibilityFeature**.

## Two Ways to Run

The system supports two data ingestion modes. Both require `agents/tfl_graph_builder.py` to be run first to build the static graph.

| | Local (polling) | UKDTC Sandbox (event-driven) |
|---|---|---|
| **Script** | `legacy/tfl_train_loader.py` | `agents/neo4j_adapter.py` |
| **Data source** | Polls TfL API directly every 30s | Subscribes to MQTT broker fed by Node-RED |
| **Writes to** | Neo4j + InfluxDB | Neo4j only |
| **Infrastructure** | Docker (Neo4j + InfluxDB) | UKDTC Sandbox (Neo4j + EMQX + Node-RED) |

For local development, use the polling approach — it is self-contained and requires no additional infrastructure beyond two Docker containers.

For the UKDTC Sandbox, uncomment and fill in the sandbox variables in your `.env` file (`NEO4J_URI`, `MQTT_PASS`, `NEO4J_PASSWORD`, etc.) and import `nodered/train_loader_flow.json` into the sandbox Node-RED instance. The adapter connects to `mosquitto.ukdtc-dtaas-uop.ukdtc.uk` via WebSockets with TLS.

## Running Locally

### 1. Start Neo4j and InfluxDB

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -v neo4j_data:/data \
  -e NEO4J_AUTH=neo4j/supersecretpassword \
  neo4j:5

docker run -d --name influxdb \
  -p 8086:8086 \
  -v influxdb2_data:/var/lib/influxdb2 \
  influxdb:2.7
```

### 2. Install dependencies

```bash
poetry install
```

### 3. Configure credentials

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

The `.env` file is gitignored. Edit it to set your credentials:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=supersecretpassword

INFLUX_URL=http://localhost:8086
INFLUX_TOKEN=              # see below
INFLUX_ORG=UKDTC
INFLUX_BUCKET=TFL
```

**Neo4j**: The default password `supersecretpassword` matches the Docker container above. Change it in `.env` if you used a different password.

**InfluxDB token**: Open http://localhost:8086 and complete the onboarding wizard (org: `UKDTC`, bucket: `TFL`). Then go to **Load Data → API Tokens**, copy the generated token, and paste it as `INFLUX_TOKEN` in your `.env`.

### 4. Build the static graph

```bash
poetry run python -m agents.tfl_graph_builder
```

This fetches all Underground lines, stations, routes, and accessibility features from the TfL API and writes them to Neo4j. Takes a few minutes due to API rate limits.

### 5. Start the train loader

```bash
poetry run python -m legacy.tfl_train_loader
```

This polls the TfL API every 30 seconds for all 11 Underground lines and writes train positions to Neo4j and InfluxDB.

### 6. Start the visualisation

```bash
poetry run uvicorn visualisation.main:app --host 0.0.0.0 --port 8000
```

There are two ways to view the map:

- **Via the server** (recommended): Open http://localhost:8000. The FastAPI app serves `index.html` at the root URL alongside the WebSocket data stream — everything from one address.
- **Via the file directly**: Open `visualisation/index.html` in a browser by dragging it in or navigating to `file:///path/to/visualisation/index.html`. This works because the HTML contains a hardcoded `ws://localhost:8000/ws/trains` WebSocket URL, and browsers permit WebSocket connections from `file://` origins. This was the original approach before the `GET /` route was added.

### 7. Verify Neo4j

Open http://localhost:7474, log in with `neo4j` / `supersecretpassword`, and run:

```cypher
MATCH (n) RETURN labels(n), count(n)
```

You should see counts for Station, Line, Route, Train, TransportOperator, and AccessibilityFeature nodes.

## DTDL V3 Ontology

The ontology in `dtdl/LondonUnderground.json` defines the following interfaces:

| Interface | Description |
|---|---|
| **Station** | A physical Underground station with coordinates and accessibility features |
| **Route** | A sequence of stations in a given direction on a line |
| **Train** | A live train with position, direction, ETA, and vehicle ID |
| **Line** | A logical line (e.g. Central, Victoria) with a colour |
| **TransportOperator** | The operating entity (TfL) |
| **AccessibilityFeature** | Station features such as lifts, toilets, and taxi ranks |

## Testing

This project uses a testing pyramid: unit tests, integration tests (require Docker Compose), and e2e tests.

### Running Tests

```bash
poetry install
poetry run pytest                # unit tests only (default)
poetry run pytest -v -s          # verbose with stdout
poetry run pytest --cov=agents --cov=legacy --cov=visualisation --cov=config --cov-report=term-missing
```

By default, `poetry run pytest` runs only unit tests (integration and e2e are excluded via `pyproject.toml` addopts).

### Integration Tests

```bash
docker compose up -d --wait
poetry run pytest -m integration -v -s
docker compose down -v
```

### Linting and Formatting

```bash
poetry run pylint agents/ legacy/ visualisation/ config.py --disable=C,R,W
poetry run black --check .
poetry run black .
poetry run mypy agents/ legacy/ visualisation/ config.py
```

## Interesting Queries

Forecast future bunching (headway < threshold):

```cypher
WITH 120 AS minSeparation

MATCH (t:Train)-[:servesRoute]->(r:Route)-[:onLine]->(l:Line)
WITH minSeparation,
     l.name AS line,
     r.routeId AS route,
     t.direction AS direction,
     t,
     datetime(t.expectedArrival) AS eta
ORDER BY line, route, direction, eta

WITH minSeparation,
     line, route, direction,
     collect({train: t, eta: eta}) AS trains

UNWIND range(1, size(trains)-1) AS i
WITH minSeparation,
     line, route, direction,
     trains[i-1] AS a,
     trains[i] AS b,
     duration.between(trains[i-1].eta, trains[i].eta).seconds AS gap

WHERE gap < minSeparation

RETURN
    line,
    route,
    direction,
    a.train.vehicleId AS trainA,
    a.eta AS etaA,
    b.train.vehicleId AS trainB,
    b.eta AS etaB,
    gap AS gapSeconds
ORDER BY gapSeconds ASC;
```

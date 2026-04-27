import asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from neo4j import GraphDatabase, exceptions as neo4j_exceptions
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from datetime import datetime
from config import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
)

# --- Neo4J and InfluxDB initialization ---
neo_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx_client.query_api()

# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server starting: Neo4J and InfluxDB connections ready")
    try:
        yield
    finally:
        neo_driver.close()
        influx_client.close()
        print("Connections closed on shutdown")

app = FastAPI(lifespan=lifespan)

# --- Serve index.html at root ---
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)

# --- Fetch stations from Neo4J ---
async def fetch_stations():
    try:
        with neo_driver.session() as session:
            result = session.run(
                "MATCH (s:Station) "
                "RETURN s.stationId AS id, s.name AS name, s.latitude AS lat, s.longitude AS lon"
            )
            stations = [
                {"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"]}
                for r in result
            ]
            return stations
    except neo4j_exceptions.Neo4jError as e:
        print("Neo4J error:", e)
        return []

# --- Fetch live trains from Neo4J ---
async def fetch_live_trains():
    try:
        with neo_driver.session() as session:
            result = session.run(
                """
                MATCH (t:Train)
                MATCH (s:Station {stationId: t.nextStationId})
                OPTIONAL MATCH (s)-[:servedByLine]->(l:Line)
                RETURN
                    t.vehicleId AS trainId,
                    t.nextStationId AS nextStationId,
                    s.latitude AS lat,
                    s.longitude AS lon,
                    l.lineId AS lineId,
                    l.name AS lineName
                """
            )

            trains = []
            for r in result:
                trains.append({
                    "trainId": r["trainId"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "lineId": r["lineId"] or "unknown",
                    "line": r["lineName"] or "Unknown",
                    "nextStation": r["nextStationId"],
                    "eta": datetime.utcnow().isoformat() + "Z"
                })

            return trains

    except neo4j_exceptions.Neo4jError as e:
        print("Neo4J error fetching trains:", e)
        return []

# --- WebSocket endpoint ---
@app.websocket("/ws/trains")
async def websocket_trains(ws: WebSocket):
    await ws.accept()
    print("WebSocket connection established")
    try:
        while True:
            stations = await fetch_stations()
            trains = await fetch_live_trains()
            payload = json.dumps({"stations": stations, "trains": trains})
            await ws.send_text(payload)
            await asyncio.sleep(5)  # Update interval
    except WebSocketDisconnect:
        print("WebSocket client disconnected")
    except Exception as e:
        print("WebSocket error, closing:", e)

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from neo4j import GraphDatabase
import time
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# ---- TfL API settings ----
TFL_BASE_URL = "https://api.tfl.gov.uk"
LINES_URL = f"{TFL_BASE_URL}/Line/Mode/tube"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ---- Global caches to reduce API requests ----
station_cache = {}
accessibility_features_of_interest = {"AccessViaLift", "TaxiRankOutsideStation", "Toilet"}

def get_lines():
    resp = requests.get(LINES_URL)
    resp.raise_for_status()
    return resp.json()

def get_stations_for_line(line_id):
    url = f"{TFL_BASE_URL}/Line/{line_id}/StopPoints"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Warning: Could not fetch stations for line {line_id}: {e}")
        return []
    return resp.json()

def fetch_station(station_id):
    if station_id in station_cache:
        return station_cache[station_id]
    url = f"{TFL_BASE_URL}/StopPoint/{station_id}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        station_cache[station_id] = resp.json()
        return station_cache[station_id]
    except requests.exceptions.HTTPError as e:
        print(f"Warning: Could not fetch station {station_id} (status {resp.status_code})")
        return None

def get_routes_for_line(line_id):
    url = f"{TFL_BASE_URL}/Line/{line_id}/Route/Sequence/inbound"
    routes = []
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        routes.append(resp.json())
    except requests.exceptions.HTTPError as e:
        if resp.status_code != 404:
            print(f"Warning: Could not fetch route sequence for line {line_id} inbound: {e}")

    url = f"{TFL_BASE_URL}/Line/{line_id}/Route/Sequence/outbound"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        routes.append(resp.json())
    except requests.exceptions.HTTPError as e:
        if resp.status_code != 404:
            print(f"Warning: Could not fetch route sequence for line {line_id} outbound: {e}")

    return routes

def create_graph():
    lines = get_lines()
    with driver.session() as session:
        # TransportOperator
        session.run("MERGE (t:TransportOperator {name: $name})", {"name": "TfL"})

        for line in lines:
            line_id = line["id"]
            line_name = line["name"]
            line_colour = line.get("colour", "")

            # Line node
            session.run("""
                MERGE (l:Line {lineId: $lineId})
                SET l.name = $lineName, l.colour = $lineColour
                WITH l
                MATCH (t:TransportOperator {name: 'TfL'})
                MERGE (t)-[:operatesLine]->(l)
            """, {"lineId": line_id, "lineName": line_name, "lineColour": line_colour})

            # Stations
            station_data = get_stations_for_line(line_id)
            for s in station_data:
                station_id = s.get("id")
                if not station_id:
                    continue
                station_name = s.get("commonName") or s.get("name") or "Unknown"
                lat = s.get("lat") or s.get("stationLat") or 0.0
                lon = s.get("lon") or s.get("stationLon") or 0.0

                # Accessibility features
                features = s.get("additionalProperties", [])
                features_of_interest = [f["key"] for f in features
                                        if f["key"] in accessibility_features_of_interest and f.get("value") == "Yes"]

                # Create Station
                session.run("""
                    MERGE (st:Station {stationId: $stationId})
                    SET st.name = $name, st.latitude = $lat, st.longitude = $lon
                    WITH st
                    MATCH (l:Line {lineId: $lineId})
                    MERGE (st)-[:servedByLine]->(l)
                """, {"stationId": station_id, "name": station_name, "lat": lat, "lon": lon, "lineId": line_id})

                # Create AccessibilityFeature nodes & relationships
                for feat in features_of_interest:
                    session.run("""
                        MERGE (af:AccessibilityFeature {name: $feat})
                        WITH af
                        MATCH (st:Station {stationId: $stationId})
                        MERGE (st)-[:hasAccessibilityFeature]->(af)
                    """, {"feat": feat, "stationId": station_id})

            # Routes
            routes_data = get_routes_for_line(line_id)
            route_counter = 0
            for seq_data in routes_data:
                for sp_seq in seq_data.get("stopPointSequences", []):
                    direction = sp_seq.get("direction", "unknown")
                    stop_points = sp_seq.get("stopPoint") or sp_seq.get("stopPoints") or []
                    if not stop_points:
                        continue
                    station_sequence = [sp.get("id") for sp in stop_points if sp.get("id")]

                    if not station_sequence:
                        continue

                    route_id = f"{line_id}-route-{route_counter}"
                    route_counter += 1
                    starting_station = station_sequence[0]
                    terminating_station = station_sequence[-1]

                    # Create Route node
                    session.run("""
                        MERGE (r:Route {routeId: $routeId})
                        SET r.direction = $direction, r.stationSequence = $stationSequence
                        WITH r
                        MATCH (l:Line {lineId: $lineId})
                        MERGE (r)-[:onLine]->(l)
                    """, {"routeId": route_id, "direction": direction, "stationSequence": station_sequence, "lineId": line_id})

                    # Connect Route endpoints
                    session.run("""
                        MATCH (r:Route {routeId: $routeId})
                        MATCH (s:Station {stationId: $start})
                        MATCH (t:Station {stationId: $end})
                        MERGE (r)-[:startingStation]->(s)
                        MERGE (r)-[:terminatingStation]->(t)
                    """, {"routeId": route_id, "start": starting_station, "end": terminating_station})

if __name__ == "__main__":
    create_graph()
    print("London Underground graph with stations, accessibility features, and routes loaded into Neo4j.")

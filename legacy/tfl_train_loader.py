import requests
import time
from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from neo4j import GraphDatabase
from config import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
    INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET,
)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def init_influx():
    client = InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG
    )
    write_api = client.write_api(write_options=SYNCHRONOUS)
    return write_api

write_api = init_influx()

# All TfL Underground line IDs
UNDERGROUND_LINES = [
    "bakerloo",
    "central",
    "circle",
    "district",
    "hammersmith-city",
    "jubilee",
    "metropolitan",
    "northern",
    "piccadilly",
    "victoria",
    "waterloo-city"
]

def write_trains_to_influx(trains, line_id):
    points = []
    for t in trains:
        vehicle_id = t.get("vehicleId")
        time_to_station = t.get("timeToStation")
        direction = t.get("direction")
        naptan_id = t.get("naptanId")
        dest_id = t.get("destinationNaptanId")
        expected_arrival = t.get("expectedArrival")

        p = (
            Point("tfl_trains")
            .tag("lineId", line_id)
            .tag("vehicleId", vehicle_id)
            .tag("direction", direction)
            .tag("currentStationId", naptan_id)
            .tag("destinationStationId", dest_id)
            .field("timeToStation", time_to_station)
            .field("expectedArrival", expected_arrival or "")
            .time(datetime.utcnow())
        )
        points.append(p)

    if points:
        write_api.write(bucket=INFLUX_BUCKET, record=points)
        print(f"Wrote {len(points)} train points for line {line_id}")

def delete_all_trains():
    with driver.session() as session:
        session.run("MATCH (t:Train) DETACH DELETE t")
    print("All Train nodes have been deleted.")


def fetch_active_trains(line_id):
    """Fetch arrivals for a specific Underground line."""
    url = f"https://api.tfl.gov.uk/Line/{line_id}/Arrivals"
    response = requests.get(url)

    if response.status_code != 200:
        print(f"Error fetching data for line {line_id}: {response.status_code}")
        return []

    trains = response.json()
    write_trains_to_influx(trains, line_id)

    # Keep only the nearest prediction per vehicle
    filtered = {}
    for train in trains:
        vid = train.get("vehicleId")
        tts = train.get("timeToStation")
        direction = train.get("direction")
        dest_id = train.get("destinationNaptanId")
        naptan_id = train.get("naptanId")

        if not direction or not dest_id or not naptan_id:
            continue

        if vid and tts is not None:
            if vid not in filtered or tts < filtered[vid]["timeToStation"]:
                filtered[vid] = train

    return list(filtered.values())


def create_train_and_link_route(tx, train, route):
    query = """
    MERGE (t:Train {vehicleId: $vehicleId})
    SET t.lineId = $lineId,
        t.direction = $direction,
        t.timestamp = $timestamp,
        t.nextStationName = COALESCE($nextStationName, $destinationName),
        t.nextStationId = COALESCE($nextStationId, $destinationStationId),
        t.secondsToNextStop = $secondsToNextStop,
        t.expectedArrival = $expectedArrival
    """

    tx.run(query,
        vehicleId=train.get("vehicleId"),
        lineId=train.get("lineId"),
        direction=train.get("direction"),
        timestamp=train.get("timestamp"),
        nextStationName=train.get("stationName"),
        nextStationId=train.get("naptanId"),
        secondsToNextStop=train.get("timeToStation"),
        destinationName=train.get("destinationName"),
        destinationStationId=train.get("destinationNaptanId"),
        expectedArrival=train.get("expectedArrival")
    )

    tx.run("""
    MATCH (t:Train {vehicleId: $vehicleId}), (r:Route {routeId: $routeId})
    MERGE (t)-[:servesRoute]->(r)
    """, vehicleId=train.get("vehicleId"), routeId=route["routeId"])

    print(f"Created Train node {train.get('vehicleId')} linked to route {route['routeId']}")


def find_matching_routes(line_id, direction, dest_id, naptan_id):
    query = """
    MATCH (r:Route)-[:onLine]->(l:Line)
    WHERE l.lineId = $lineId
      AND r.direction = $direction
      AND last(r.stationSequence) = $destinationNaptanId
      AND $trainNaptanId IN r.stationSequence
    RETURN r
    """

    with driver.session() as session:
        result = session.run(query,
            lineId=line_id,
            direction=direction,
            destinationNaptanId=dest_id,
            trainNaptanId=naptan_id
        )
        return [record["r"] for record in result]


def load_trains_for_line(line_id):
    print(f"\nFetching active trains for **{line_id}**...")
    trains = fetch_active_trains(line_id)

    if not trains:
        print(f"No active trains found for {line_id}.")
        return

    print(f"Processing {len(trains)} trains for {line_id}...")

    with driver.session() as session:
        with session.begin_transaction() as tx:
            for train in trains:
                vid = train.get("vehicleId")
                direction = train.get("direction")
                dest = train.get("destinationNaptanId")
                naptan = train.get("naptanId")

                if not direction or not dest or not naptan:
                    print(f"Skipping train {vid} due to missing data.")
                    continue

                routes = find_matching_routes(line_id, direction, dest, naptan)

                if len(routes) == 1:
                    create_train_and_link_route(tx, train, routes[0])
                elif len(routes) > 1:
                    print(f"Multiple route matches for {vid}, skipping.")
                else:
                    print(f"No matching route for {vid}, skipping.")


def load_all_lines():
    delete_all_trains()
    for line_id in UNDERGROUND_LINES:
        load_trains_for_line(line_id)
    print("\n✔ Finished loading all Underground lines.")

def main():
    print("Starting 30-second refresh loop for London Underground trains...\n")
    try:
        while True:
            start = time.time()

            print("\n=== Refreshing Train Graph ===")
            load_all_lines()
            print("=== Refresh complete ===")

            elapsed = time.time() - start
            sleep_time = max(0, 30 - elapsed)

            print(f"Next refresh in {sleep_time:.1f} seconds...")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\nStopping refresh loop. Goodbye!")

if __name__ == "__main__":
    main()

import paho.mqtt.client as mqtt
import json
import requests
from neo4j import GraphDatabase

# Single root hostname (change this ONCE)
ROOT_HOST = "ukdtc-dtaas-uop.ukdtc.uk"

# MQTT / Mosquitto
MQTT_HOST = f"mosquitto.{ROOT_HOST}"
MQTT_PORT = 9443
MQTT_TOPIC = "tfl/#"
MQTT_USER = "ukdtc"
MQTT_PASS = ""

# Neo4j
NEO4J_URL = f"bolt+s://neo4j.{ROOT_HOST}:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = ""
driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))

# Callback for when the client connects to the broker
def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    # Subscribe to topic(s) here
    client.subscribe(MQTT_TOPIC) 

# Callback for when a message is received
def on_message(client, userdata, msg):
    print(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
    trains = json.loads(msg.payload.decode())
    print(trains)
    if trains:
        if trains[0]["lineId"]:
            current_line_id = trains[0]["lineId"]
            delete_trains(current_line_id)
            active_trains = fetch_active_trains(trains, current_line_id)
            if not active_trains:
                print(f"No active trains found for {current_line_id}.")
                return
            load_trains_for_line(active_trains, current_line_id)

def load_trains_for_line(trains, line_id):
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

def delete_trains(line_id):
    query = """
    MATCH (t:Train)-[:servesRoute]->(r:Route)-[:onLine]->(l:Line {lineId: $lineId})
    DETACH DELETE t;
    """
    with driver.session() as session:
        session.run(query,
                    lineId=line_id)
    print(f"Train nodes on {line_id} have been deleted.")

def fetch_active_trains(trains, line_id):
    """Fetch arrivals for a specific Underground line."""
    url = f"https://api.tfl.gov.uk/Line/{line_id}/Arrivals"
    response = requests.get(url)

    if response.status_code != 200:
        print(f"Error fetching data for line {line_id}: {response.status_code}")
        return []

    trains = response.json()

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



def main():

    client = mqtt.Client(transport="websockets",client_id="neo4j-adapter")
    client.username_pw_set(username=MQTT_USER, password=MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.tls_set()
    client.tls_insecure_set(True)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_forever()

if __name__ == "__main__":
    main()

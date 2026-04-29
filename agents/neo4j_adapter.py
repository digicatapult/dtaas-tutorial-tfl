import paho.mqtt.client as mqtt
import json
import requests
from neo4j import GraphDatabase
from agents.neo4j_utils import find_matching_routes, create_train_and_link_route
from config import (
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_PASSWORD,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TOPIC,
    MQTT_USER,
    MQTT_PASS,
)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


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
        current_line_id = trains[0].get("lineId")
        if current_line_id:
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

                routes = find_matching_routes(driver, line_id, direction, dest, naptan)

                if len(routes) == 1:
                    create_train_and_link_route(tx, train, routes[0])
                elif len(routes) > 1:
                    print(f"Multiple route matches for {vid}, skipping.")
                else:
                    print(f"No matching route for {vid}, skipping.")


def delete_trains(line_id):
    query = """
    MATCH (t:Train)-[:servesRoute]->(r:Route)-[:onLine]->(l:Line {lineId: $lineId})
    DETACH DELETE t;
    """
    with driver.session() as session:
        session.run(query, lineId=line_id)
    print(f"Train nodes on {line_id} have been deleted.")


def fetch_active_trains(trains, line_id):
    """Fetch arrivals for a specific Underground line."""
    url = f"https://api.tfl.gov.uk/Line/{line_id}/Arrivals"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        status_code = getattr(e.response, "status_code", "Unknown") if hasattr(e, "response") and e.response is not None else "Connection Error"
        print(f"Error fetching data for line {line_id} (status {status_code}): {e}")
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

    client = mqtt.Client(transport="websockets", client_id="neo4j-adapter")
    client.username_pw_set(username=MQTT_USER, password=MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.tls_set()
    client.tls_insecure_set(True)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()

import os
from dotenv import load_dotenv

load_dotenv()

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# InfluxDB
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "UKDTC")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "TFL")

# UKDTC Sandbox (MQTT / Node-RED)
UKDTC_ROOT_HOST = os.getenv("UKDTC_ROOT_HOST", "ukdtc-dtaas-uop.ukdtc.uk")
MQTT_HOST = os.getenv("MQTT_HOST", f"mosquitto.{UKDTC_ROOT_HOST}")
MQTT_PORT = int(os.getenv("MQTT_PORT", "9443"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "tfl/#")
MQTT_USER = os.getenv("MQTT_USER", "ukdtc")
MQTT_PASS = os.getenv("MQTT_PASS", "")

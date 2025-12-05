# dtaas-tutorial-tfl
DTaaS Tutorial using Transport for London API

## London Underground DTDL V3 Ontology

This ontology represents the London Underground network in **Azure Digital Twins (DTDL V3)**, including stations, lines, routes, trains, operators, and accessibility features.

---

### 1. Station
- **Represents:** A single Underground station.
- **Properties:** 
  - `name` – The station’s name.
  - `stationId` – Unique identifier for the station.
  - `latitude` / `longitude` – Geographical coordinates.
- **Relationships:**
  - `servedByLine` – Links to lines that stop at this station.
  - `startingStation` / `terminatingStation` – Links to routes starting or ending at this station.
  - `hasAccessibilityFeature` – Links to accessibility features available at the station.

---

### 2. Route
- **Represents:** A train route connecting a sequence of stations.
- **Properties:** 
  - `routeId` – Unique identifier for the route.
  - `direction` – Direction of travel.
  - `stationSequence` – Ordered list of station IDs along the route.
- **Relationships:** 
  - `onLine` – Links the route to a line.
  - `servesRoute` – Links to trains currently serving this route.

---

### 3. Train
- **Represents:** An individual train running on the network.
- **Properties:** 
  - `lineId` – The line the train belongs to.
  - `direction` – Direction of travel.
  - `timestamp` – Current observation timestamp.
  - `secondsToNextStop` – Time until the train reaches its next station.
  - `expectedArrival` – Scheduled or predicted arrival time at the next station.
  - `nextStationId` / `nextStationName` – Next station on the route.
  - `vehicleId` – Unique identifier for the train.
- **Relationships:** 
  - `servesRoute` – Links to the route the train is serving.

---

### 4. Line
- **Represents:** A physical or operational subway line.
- **Properties:** 
  - `lineId` – Unique identifier for the line.
  - `name` – Line name (e.g., "Central").
  - `colour` – Official line color for visualization.
- **Relationships:** 
  - `servedByLine` – Links to stations served by the line.
  - `onLine` – Links to routes on this line.
  - `operatesLine` – Links to the transport operator running the line.

---

### 5. TransportOperator
- **Represents:** The organization managing a line (e.g., TfL).
- **Properties:** 
  - `name` – Operator name.
- **Relationships:** 
  - `operatesLine` – Links to the lines operated by this organization.

---

### 6. AccessibilityFeature
- **Represents:** Accessibility capabilities available at stations (e.g., lifts, step-free access).
- **Properties:** 
  - `name` – Name of the feature.
- **Relationships:** 
  - `hasAccessibilityFeature` – Links to stations offering this feature.

# Neo4J and InfluxDB Setup
Use a UKDTC DTaaS Design Studio environment, or alternatively run Neo4j and InfluxDB locally using docker.

E.g.

docker pull influxdb:2.7

docker run -d --name influxdb -p 8086:8086 -v influxdb2_data:/var/lib/influxdb2 -e INFLUXDB_ADMIN_USER=admin -e INFLUXDB_ADMIN_PASSWORD=supersecretpassword -e INFLUXDB_BUCKET=mybucket -e INFLUXDB_ORG=myorg influxdb:2.7

docker pull neo4j:5

docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -v neo4j_data:/data -e NEO4J_AUTH=neo4j/supersecretpassword neo4j:5

# Build the Neo4j Graph
The ontology expresses mostly static interfaces (Station, Route, AccessibilityFeature, TransportOperator, Line). There is one dynamic interface (Train). To run the tutorial we first create the static graph and then update the graph dynamically with train data.

[1] python tfl_graph_builder.py

[2] python tfl_train_loader.py


# Interesting Queries
[1] Forecast future bunching (headway < threshold)

```
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



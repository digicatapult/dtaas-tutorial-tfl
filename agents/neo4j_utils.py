def find_matching_routes(driver, line_id, direction, dest_id, naptan_id):
    """Shared utility to find routes matching a train's path."""
    query = """
    MATCH (r:Route)-[:onLine]->(l:Line)
    WHERE l.lineId = $lineId
      AND r.direction = $direction
      AND last(r.stationSequence) = $destinationNaptanId
      AND $trainNaptanId IN r.stationSequence
    RETURN r
    """
    with driver.session() as session:
        result = session.run(
            query,
            lineId=line_id,
            direction=direction,
            destinationNaptanId=dest_id,
            trainNaptanId=naptan_id,
        )
        return [record["r"] for record in result]


def create_train_and_link_route(tx, train, route):
    """Shared utility to upsert a Train node and link it to a Route."""
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
    tx.run(
        query,
        vehicleId=train.get("vehicleId"),
        lineId=train.get("lineId"),
        direction=train.get("direction"),
        timestamp=train.get("timestamp"),
        nextStationName=train.get("stationName"),
        nextStationId=train.get("naptanId"),
        secondsToNextStop=train.get("timeToStation"),
        destinationName=train.get("destinationName"),
        destinationStationId=train.get("destinationNaptanId"),
        expectedArrival=train.get("expectedArrival"),
    )

    tx.run(
        """
    MATCH (t:Train {vehicleId: $vehicleId}), (r:Route {routeId: $routeId})
    MERGE (t)-[:servesRoute]->(r)
    """,
        vehicleId=train.get("vehicleId"),
        routeId=route["routeId"],
    )

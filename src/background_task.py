"""
Background Task service for Hurtec integration.

This module handles background processing including:
- GPS data fetching from the Peplink router
- Processing vehicle data
- MQTT messaging integration
- Periodic system health checks
- Battery monitoring and power mode management
"""

import time
from datetime import datetime, timezone, timedelta
import threading
import logging
from typing import Union, Optional, cast, Dict, Tuple, Any
import os
import json
import uuid
import socket

import paho.mqtt.client as mqtt  # pylint: disable=import-error
import requests  # pylint: disable=import-error

from data_access import (
    purge_old_messages,
    purge_old_gps_data,
    purge_old_device_data,
    store_gps_coordinates,
    GPSCoordinates,
)
from timestamp_util import (
    UTC_TIME_FORMAT,
    get_utc_now,
    get_current_timestamp_utc,
    get_mqtt_timestamp,
    ensure_mqtt_timestamp,
)
import logger_setup
from mqtt_utils import connect_mqtt_client
from secrets_util import load_secrets
from models import (
    SessionLocal,
    GPSData,
    OutboundGPSData,
    VehicleData,
    OutboundVehicleData,
)
from location_util import location_is_different, GpsData as GpsDataDict

# Import the vehicle data utilities and router utilities
import vehicle_data_utils as vdu
from router_utils import router_login, re_authenticate
import config_util
import mock_gps
import mock_vehicle

# Import battery monitoring
from battery_monitor import BatteryMonitor

logger_setup.set_process_name("background_task")


def get_timestamp() -> str:
    """Get current UTC timestamp formatted for logging."""
    return get_current_timestamp_utc()


required_certs = ["ca.pem", "cert.crt", "private.key"]


def _get_gps_response(
    session: requests.Session, endpoint: str
) -> Tuple[requests.Response, bool]:
    """Get GPS response from the router API, handling authentication errors."""
    try:
        response = session.get(endpoint, verify=False)
        logging.debug("GPS API response status code: %s", response.status_code)

        # Return early if unauthorized
        if response.status_code == 401:
            return response, True

        return response, False
    except Exception as req_err:
        logging.error("Error getting GPS response: %s", req_err)
        raise


def _process_gps_data(gps_data: dict[str, Any]) -> Optional[GPSCoordinates]:
    """Process GPS data and extract coordinates if valid."""
    if str(gps_data.get("stat", "")).lower() != "ok":
        error_code = gps_data.get("code", "unknown")
        error_msg = gps_data.get("message", "No message")

        if error_code == 401 and error_msg == "Unauthorized":
            # Signal that re-authentication is needed
            return None

        logging.error("Failed to fetch GPS data via API call, received: %s", gps_data)
        return None

    response_data = gps_data.get("response", {})
    location = response_data.get("location", {})

    # Basic validation of required fields
    lat = location.get("latitude")
    lng = location.get("longitude")
    timestamp = location.get("timestamp")

    if lat is None or lng is None or timestamp is None:
        logging.warning("Received incomplete GPS data from router: %s", location)
        return None

    return GPSCoordinates(
        lat,
        lng,
        location.get("altitude"),
        location.get("speed", 0.0),
        location.get("heading", -1),
        location.get("pdop"),
        location.get("hdop"),
        location.get("vdop"),
        timestamp,
    )


def fetch_router_gps(
    session: requests.Session, router_ip: str, credentials: dict[str, str]
) -> tuple[requests.Session, Optional[GPSCoordinates]]:
    """
    Fetch GPS data from the router API.

    Returns a tuple of (session, coordinates) where session may be a new session
    if re-authentication was required, and coordinates may be None if the request failed.
    """
    # Use the correct endpoint to obtain GPS/location information
    endpoint = f"https://{router_ip}/api/info.location"

    try:
        # Get initial response, handling HTTP 401
        response, needs_auth = _get_gps_response(session, endpoint)

        # Handle HTTP 401 Unauthorized by getting a new session
        if needs_auth:
            try:
                new_session = re_authenticate(router_ip, credentials)
                response, _ = _get_gps_response(new_session, endpoint)
                session = new_session  # Update session to be returned
            except Exception:
                return session, None

        # Check for success status code
        if response.status_code != 200:
            logging.error(
                "Failed to fetch GPS data via API call, status code: %s",
                response.status_code,
            )
            return session, None

        # Parse JSON response
        try:
            gps_data = response.json()
        except Exception as json_err:
            logging.error("Failed to decode GPS API response as JSON: %s", json_err)
            return session, None

        logging.debug("Full GPS API response: %s", gps_data)

        # Process GPS data
        gps_coordinates = _process_gps_data(gps_data)

        # Handle API-level 401 that wasn't caught by HTTP status code
        if gps_coordinates is None and gps_data.get("code") == 401:
            try:
                new_session = re_authenticate(router_ip, credentials)
                response, _ = _get_gps_response(new_session, endpoint)

                if response.status_code == 200:
                    new_gps_data = response.json()
                    gps_coordinates = _process_gps_data(new_gps_data)
                    session = new_session

            except Exception:
                return session, None

        return session, gps_coordinates

    except Exception as general_err:
        logging.exception("Unexpected error in fetch_router_gps: %s", general_err)
        return session, None


def gps_polling_wrapper(
    router_ip: str, session: requests.Session, credentials: dict[str, str]
) -> None:
    while True:
        try:
            # Updated to unpack both the session and gps result
            session, gps_result = fetch_router_gps(session, router_ip, credentials)
            if gps_result:
                store_gps_coordinates(gps_result)
                logging.info(
                    "Stored GPS coordinates: (%s, %s, alt=%s)",
                    gps_result.lat,
                    gps_result.lng,
                    gps_result.alt,
                )
        except Exception as poll_err:
            logging.error("Error fetching/storing GPS coordinates: %s", poll_err)
        time.sleep(5)


def on_disconnect(
    client: mqtt.Client,
    userdata: dict[str, Union[str, int, float, bool, None]],
    disconnect_flags: dict[str, Union[str, int, float, bool, None]],
    reason_code: int,
    properties: Optional[dict[str, Union[str, int, float, bool, None]]] = None,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> None:
    """Handle MQTT client disconnection with retry logic.

    Args:
        client: MQTT client instance
        userdata: User data dictionary
        disconnect_flags: Disconnect flags dictionary
        reason_code: Disconnect reason code
        properties: Additional properties dictionary
        max_retries: Maximum number of reconnection attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 5)
    """
    if properties is None:
        properties = {}
    logging.error(
        "MQTT disconnected with flags %s, user %s, reason_code %s, properties %s.",
        disconnect_flags,
        userdata,
        reason_code,
        properties,
    )

    attempt = 0
    while max_retries < 0 or attempt < max_retries:
        result = client.reconnect()
        if result == mqtt.MQTT_ERR_SUCCESS:
            logging.info("Reconnected to MQTT broker.")
            return

        if max_retries >= 0:
            remaining_attempts = max_retries - attempt - 1
            if remaining_attempts > 0:
                logging.error(
                    "Reconnection attempt %d failed with error code %s. %d attempts remaining. Retrying in %d seconds...",
                    attempt + 1,
                    result,
                    remaining_attempts,
                    retry_delay,
                )
            else:
                logging.error(
                    "Reconnection attempt %d failed with error code %s. No more retries.",
                    attempt + 1,
                    result,
                )
        else:
            logging.error(
                "Reconnection attempt %d failed with error code %s. Retrying in %d seconds...",
                attempt + 1,
                result,
                retry_delay,
            )
        time.sleep(retry_delay)
        attempt += 1

    if max_retries >= 0:
        logging.error("Failed to reconnect after %d attempts.", max_retries)


def init_mqtt_client(
    broker_address: str,
    port: int,
    client_id: str,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> Optional[mqtt.Client]:
    """Initialize and connect an MQTT client.

    Args:
        broker_address: The broker address to connect to
        port: The port to connect on
        client_id: The client ID to use
        max_retries: Maximum number of connection attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 5)

    Returns:
        Optional[mqtt.Client]: The connected client if successful, None otherwise
    """
    # Add a unique suffix to the client_id to prevent conflicts
    unique_client_id = f"{client_id}_{str(uuid.uuid4())[:8]}"
    logging.info("Initializing MQTT client with ID: %s", unique_client_id)

    client = mqtt.Client(client_id=unique_client_id, protocol=mqtt.MQTTv5)
    client.on_disconnect = on_disconnect  # type: ignore
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # Set socket options for more reliable connections
    client.socket_options = (
        # TCP Keepalive: Enable TCP keepalive
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    )

    # Use the connect_mqtt_client function with keepalive=60 and default stability_delay
    if connect_mqtt_client(
        client,
        broker_address,
        port,
        max_retries,
        retry_delay,
        keepalive=60,
        # Using default stability_delay of 2.0 seconds
    ):
        return client
    return None


def start_cleanup_thread() -> threading.Thread:
    """Start a background thread for periodic cleanup tasks.

    Returns:
        threading.Thread: The started cleanup thread.
    """
    stop_event = threading.Event()

    def cleanup_periodically() -> None:
        while not stop_event.is_set():
            try:
                purge_old_messages()
                purge_old_gps_data()
                purge_old_device_data()
                purge_old_vehicle_data()
                logging.info(
                    "Purged old messages, GPS data, device data, and vehicle data."
                )
            except Exception as cleanup_err:
                logging.error("Error in cleanup_periodically: %s", cleanup_err)
            stop_event.wait(timeout=300)  # Use event's wait instead of time.sleep

    cleanup_thread = threading.Thread(
        target=cleanup_periodically, daemon=True, name="cleanup_thread"
    )
    cleanup_thread.stop_event = stop_event  # type: ignore  # Add the event as an attribute
    cleanup_thread.start()
    logging.info("Started cleanup thread.")
    return cleanup_thread


def obtain_router_session(
    max_retries: int = 3,
    retry_delay: int = 60,
) -> tuple[str, Union[requests.Session, None], dict[str, str]]:
    """Obtain a router session with retry logic.

    Args:
        max_retries: Maximum number of retry attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 60)

    Returns:
        tuple[str, Union[requests.Session, None], dict[str, str]]: Router IP, session, and credentials
    """
    attempt = 0
    while max_retries < 0 or attempt < max_retries:
        try:
            # Load secrets from mounted secrets file
            secrets = load_secrets()
            peplink_api = cast(Dict[str, str], secrets.get("peplink_api", {}))
            logging.info("Successfully loaded peplink_api from secrets file")
            router_ip = peplink_api.get("router_ip")
            router_userid = peplink_api.get("router_userid")
            router_password = peplink_api.get("router_password")

            if not router_ip or not router_userid or not router_password:
                logging.error("Router IP, userid, or password not found in secrets.")
                return "", None, {}

            credentials = {
                "router_userid": router_userid,
                "router_password": router_password,
            }

            session = router_login(router_ip, router_userid, router_password)
            if session:
                return router_ip, session, credentials

        except Exception as session_err:
            if max_retries >= 0:
                remaining_attempts = max_retries - attempt - 1
                if remaining_attempts > 0:
                    logging.error(
                        "Router login attempt %d failed: %s. %d attempts remaining. Retrying in %d seconds...",
                        attempt + 1,
                        session_err,
                        remaining_attempts,
                        retry_delay,
                    )
                else:
                    logging.error(
                        "Router login attempt %d failed: %s. No more retries.",
                        attempt + 1,
                        session_err,
                    )
            else:
                logging.error(
                    "Router login attempt %d failed: %s. Retrying in %d seconds...",
                    attempt + 1,
                    session_err,
                    retry_delay,
                )
            time.sleep(retry_delay)
        attempt += 1

    return "", None, {}


def _create_gps_dict(record: GPSData) -> GpsDataDict:
    """Convert a GPSData record to a dictionary format.

    Timestamps are in seconds since epoch (integer) following the standardized convention.
    """
    return cast(
        GpsDataDict,
        {
            "ts": ensure_mqtt_timestamp(
                record.location_timestamp
            ),  # Ensure seconds since epoch
            "lat": record.latitude,
            "lng": record.longitude,
            "spd": record.speed,
            "acc": record.pdop,
        },
    )


def _get_last_outbound_data() -> tuple[Optional[OutboundGPSData], list[GPSData]]:
    """Retrieve last outbound time and new GPS records since then."""
    with SessionLocal() as session:
        last_outbound = (
            session.query(OutboundGPSData)
            .order_by(OutboundGPSData.last_sent.desc())
            .first()
        )
        last_time = (
            last_outbound.last_sent
            if last_outbound
            else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        gps_records = (
            session.query(GPSData)
            .filter(GPSData.timestamp >= last_time)
            .order_by(GPSData.timestamp)
            .all()
        )
    return last_outbound, gps_records


def _process_new_locations(
    gps_records: list[GPSData], last_outbound: Optional[OutboundGPSData]
) -> list[GpsDataDict]:
    """Process GPS records and return significant location changes."""
    if not gps_records:
        return []

    payload_array = []
    if not last_outbound:
        # First time case: include all records
        return [_create_gps_dict(record) for record in gps_records]

    # Use first record as previous (it was the last one sent)
    previous = _create_gps_dict(gps_records[0])

    # Process remaining records
    for record in gps_records[1:]:
        current = _create_gps_dict(record)
        comparison = location_is_different(current, previous)
        if comparison.is_different:
            payload_array.append(current)
            logging.info("Location changed: %s", ", ".join(comparison.reasons))
        previous = current

    return payload_array


def _handle_heartbeat(
    last_outbound: Optional[OutboundGPSData], gps_records: list[GPSData]
) -> Optional[GpsDataDict]:
    """Handle heartbeat message if needed."""
    if not last_outbound or not gps_records:
        return None

    time_since_last = (
        datetime.now(timezone.utc) - last_outbound.last_sent
    ).total_seconds()
    if time_since_last >= 3600:
        latest_record = gps_records[-1]
        heartbeat = _create_gps_dict(latest_record)
        logging.info("Sending heartbeat GPS location update (no changes in last hour)")
        return heartbeat
    return None


def process_gps_outbound(client: mqtt.Client) -> None:
    """Process and publish outbound GPS data if there are new significant changes."""
    last_outbound, gps_records = _get_last_outbound_data()

    if len(gps_records) <= 1:
        logging.info("No new GPS updates to publish.")
        return

    payload_array = _process_new_locations(gps_records, last_outbound)

    if not payload_array:
        heartbeat = _handle_heartbeat(last_outbound, gps_records)
        if heartbeat:
            payload_array = [heartbeat]
        else:
            minutes_since_last = (
                int(
                    (
                        datetime.now(timezone.utc) - last_outbound.last_sent
                    ).total_seconds()
                    / 60
                )
                if last_outbound
                else 0
            )
            logging.info(
                (
                    "No new significant GPS changes in last %d minutes."
                    if last_outbound
                    else "No significant GPS changes ever."
                ),
                minutes_since_last,
            )
            return

    # Publish to MQTT with wrapped payload
    try:
        payload_json = json.dumps({"loc": payload_array})
        client.publish("out/gps", payload_json)

        # Record outbound message
        with SessionLocal() as session:
            new_outbound = OutboundGPSData(
                last_sent=get_utc_now(), payload=payload_array
            )
            session.add(new_outbound)
            session.commit()
        logging.info("Published outbound GPS message to topic out/gps.")
    except Exception as publish_err:
        logging.error("Failed to publish outbound GPS message: %s", publish_err)


def start_gps_outbound_thread(client: Optional[mqtt.Client]) -> threading.Thread:
    """Start the GPS outbound thread."""

    def send_gps_data() -> None:
        while True:
            try:
                if client is not None:
                    process_gps_outbound(client)
            except Exception as outbound_err:
                logging.error("Error processing GPS outbound: %s", outbound_err)
            time.sleep(30)

    thread = threading.Thread(
        target=send_gps_data,
        name="gps_outbound_thread",
        daemon=True,
    )
    thread.start()
    logging.info(
        "Started GPS outbound thread to process and send messages every 30 seconds."
    )
    return thread


def vehicle_data_polling_wrapper(
    router_ip: str, session: requests.Session, credentials: dict[str, str]
) -> None:
    """Periodically poll for vehicle data and store it in the database."""
    last_vehicle_data: Optional[Dict[str, Any]] = None

    while True:
        try:
            session, raw_data = vdu.fetch_router_vehicle_data(
                session, router_ip, credentials
            )
            if not raw_data:
                time.sleep(5)
                continue

            vehicle_data = vdu.parse_vehicle_data(raw_data)
            if not vehicle_data:
                time.sleep(5)
                continue

            if vdu.should_store_vehicle_data(vehicle_data, last_vehicle_data):
                stored_data = vdu.store_vehicle_data(vehicle_data)
                if stored_data:
                    vdu.log_new_vehicle_data(vehicle_data)
                    last_vehicle_data = vehicle_data.copy()
            else:
                logging.debug("Vehicle data unchanged, not storing.")

        except Exception as poll_err:
            logging.error("Error fetching/storing vehicle data: %s", poll_err)

        # Poll every 5 seconds
        time.sleep(5)


def _get_last_outbound_vehicle_data() -> (
    tuple[Optional[OutboundVehicleData], list[VehicleData]]
):
    """Retrieve last outbound time and new vehicle records since then."""
    with SessionLocal() as session:
        last_outbound = (
            session.query(OutboundVehicleData)
            .order_by(OutboundVehicleData.last_sent.desc())
            .first()
        )
        last_time = (
            last_outbound.last_sent
            if last_outbound
            else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        vehicle_records = (
            session.query(VehicleData)
            .filter(VehicleData.timestamp >= last_time)
            .order_by(VehicleData.timestamp)
            .all()
        )
    return last_outbound, vehicle_records


def _handle_vehicle_heartbeat(
    last_outbound: Optional[OutboundVehicleData], vehicle_records: list[VehicleData]
) -> Optional[Dict[str, Any]]:
    """Handle heartbeat message if needed."""
    if not last_outbound or not vehicle_records:
        return None

    time_since_last = (
        datetime.now(timezone.utc) - last_outbound.last_sent
    ).total_seconds()
    if time_since_last >= 3600:
        latest_record = vehicle_records[-1]
        heartbeat = vdu.create_vehicle_payload(latest_record)
        logging.info("Sending heartbeat vehicle data update (no changes in last hour)")
        return heartbeat
    return None


def process_vehicle_outbound(client: mqtt.Client) -> None:
    """Process and publish outbound vehicle data if there are new significant changes."""
    last_outbound, vehicle_records = _get_last_outbound_vehicle_data()

    # If there are no records at all, just return
    if not vehicle_records:
        logging.info("No vehicle data to publish.")
        return

    # Get the last payload that was sent
    last_payload = None
    if last_outbound and last_outbound.payload:
        try:
            if isinstance(last_outbound.payload, list) and last_outbound.payload:
                last_payload = last_outbound.payload[-1]
            elif isinstance(last_outbound.payload, dict):
                last_payload = last_outbound.payload
        except Exception as e:
            logging.error("Error processing last payload: %s", e)
            last_payload = None

    # Detect changes since last payload
    payload_array = vdu.detect_vehicle_data_changes(vehicle_records, last_payload)

    # If no changes detected but we have new records and no previous outbound,
    # include all records (this should be handled by detect_vehicle_data_changes now)
    if not payload_array and not last_outbound and vehicle_records:
        # This is a fallback in case detect_vehicle_data_changes didn't include all records
        payload_array = [
            vdu.create_vehicle_payload(record) for record in vehicle_records
        ]
        logging.info(
            "Including all %d vehicle data records as initial records",
            len(vehicle_records),
        )

    # If still no changes, check if we need a heartbeat
    if not payload_array:
        heartbeat = _handle_vehicle_heartbeat(last_outbound, vehicle_records)
        if heartbeat:
            payload_array = [heartbeat]
        else:
            minutes_since_last = (
                int(
                    (
                        datetime.now(timezone.utc) - last_outbound.last_sent
                    ).total_seconds()
                    / 60
                )
                if last_outbound
                else 0
            )
            logging.info(
                "No new vehicle data changes in last %d minutes.",
                minutes_since_last,
            )
            return

    try:
        # Log the changes we're about to send
        logging.info("Sending vehicle data changes: %s", payload_array)

        payload_json = json.dumps({"vehicle": payload_array})
        client.publish("out/vehicle", payload_json)

        with SessionLocal() as session:
            new_outbound = OutboundVehicleData(
                last_sent=get_utc_now(), payload=payload_array
            )
            session.add(new_outbound)
            session.commit()
        logging.info("Published outbound vehicle message to topic out/vehicle.")
    except Exception as publish_err:
        logging.error("Failed to publish outbound vehicle message: %s", publish_err)


def purge_old_vehicle_data() -> None:
    """Purge old vehicle data from the database."""
    try:
        with SessionLocal() as session:
            # Keep data from the last 7 days
            cutoff = get_utc_now() - timedelta(days=7)
            deleted = (
                session.query(VehicleData)
                .filter(VehicleData.timestamp < cutoff)
                .delete()
            )
            session.commit()
        logging.info("Purged %d old vehicle data records.", deleted)
    except Exception as purge_err:
        logging.error("Error purging old vehicle data: %s", purge_err)


def start_vehicle_outbound_thread(client: Optional[mqtt.Client]) -> threading.Thread:
    """Start the vehicle outbound thread."""
    stop_event = threading.Event()

    def send_vehicle_data() -> None:
        while not stop_event.is_set():
            try:
                if client is not None:
                    process_vehicle_outbound(client)
            except Exception as outbound_err:
                logging.error("Error processing vehicle outbound: %s", outbound_err)
            time.sleep(30)

    thread = threading.Thread(
        target=send_vehicle_data,
        name="vehicle_outbound_thread",
        daemon=True,
    )
    thread.stop_event = stop_event  # type: ignore
    thread.start()
    logging.info(
        "Started vehicle data outbound thread to process and send messages every 30 seconds."
    )
    return thread


def start_background_tasks(
    broker_address: str,
    port: int,
    client_id: str,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> Optional[tuple[threading.Thread, threading.Thread, threading.Thread]]:
    """Start all background tasks.

    Args:
        broker_address: MQTT broker address
        port: MQTT broker port
        client_id: MQTT client ID
        max_retries: Maximum number of connection attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 5)

    Returns:
        Optional[tuple[threading.Thread, threading.Thread, threading.Thread]]:
            The started threads (cleanup, GPS, vehicle) if successful, None if MQTT connection fails
    """
    # Start cleanup thread
    cleanup_thread = start_cleanup_thread()

    # Initialize MQTT client
    client = init_mqtt_client(broker_address, port, client_id, max_retries, retry_delay)
    if client is None:
        cleanup_thread.stop_event.set()  # type: ignore
        return None

    # Start GPS and vehicle outbound threads
    gps_thread = start_gps_outbound_thread(client)
    vehicle_thread = start_vehicle_outbound_thread(client)

    return cleanup_thread, gps_thread, vehicle_thread


def run_background_task() -> None:
    """Run the background task, initializing all required components.

    This function:
    1. Initializes the MQTT client
    2. Starts the GPS outbound thread
    3. Starts the vehicle outbound thread
    4. Starts the cleanup thread
    5. Starts the battery monitor thread
    6. In normal mode:
       a. Obtains a router session
       b. Starts the GPS polling thread
       c. Starts the vehicle data polling thread
    7. In mock mode:
       a. Starts the mock GPS generator
    8. Keeps the main thread alive
    """
    try:
        # Get MQTT broker address from environment or use default
        broker_address = config_util.get_mqtt_broker_address()
        port = 1883
        client_id = "background_task"

        # Initialize MQTT client
        client = init_mqtt_client(broker_address, port, client_id)
        if not client:
            logging.error("Failed to initialize MQTT client. Exiting.")
            return

        # Start common threads for both normal and mock modes
        start_gps_outbound_thread(client)
        start_vehicle_outbound_thread(client)
        start_cleanup_thread()

        # Start the battery monitor thread
        battery_thread = threading.Thread(target=run_battery_monitor, daemon=True)
        battery_thread.start()
        logging.info("Started battery monitoring for power mode management")

        # Check if we're in mock mode
        if config_util.is_mock_mode():
            logging.info(
                "Running Background Task in MOCK MODE - simulating GPS data in Gold Coast, Australia"
            )

            # In mock mode, we'll simulate GPS data and vehicle data
            # Start the mock GPS generator from the dedicated module
            mock_gps.start_mock_gps_generator()

            # Start the mock vehicle data generator
            mock_vehicle.start_mock_vehicle_generator()

            # In mock mode, we don't connect to the router at all
            # We'll just log a message to indicate that we're not connecting
            logging.info("Mock mode: Not connecting to router for GPS or vehicle data")

            # Keep main thread alive
            while True:
                time.sleep(1)
        else:
            # Normal mode - connect to real router for GPS data
            # Get router session
            router_ip, router_session, credentials = obtain_router_session()
            if not router_session:
                logging.error("Failed to obtain router session. Exiting.")
                return

            # Start GPS polling thread
            gps_thread = threading.Thread(
                target=gps_polling_wrapper,
                args=(router_ip, router_session, credentials),
                daemon=True,
            )
            gps_thread.start()
            logging.info("Started GPS polling thread using router session.")

            # Start vehicle data polling thread
            vehicle_thread = threading.Thread(
                target=vehicle_data_polling_wrapper,
                args=(router_ip, router_session, credentials),
                daemon=True,
            )
            vehicle_thread.start()
            logging.info("Started vehicle data polling thread.")

            # Keep main thread alive
            while True:
                time.sleep(1)
    except Exception as err:
        logging.error("Error in background task: %s", err)
        raise


def run_battery_monitor() -> None:
    """Run the battery monitoring service in a separate thread."""
    try:
        from battery_monitor import start_battery_monitor_thread

        return start_battery_monitor_thread(
            mqtt_broker_address=os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto")
        )
    except Exception as e:
        logging.error(f"Error in battery monitor: {e}")
        return None


if __name__ == "__main__":
    while True:
        try:
            run_background_task()
        except Exception as main_err:
            logging.error(
                "Background task failed with error: %s. Restarting in 10 seconds...",
                main_err,
            )
            time.sleep(10)

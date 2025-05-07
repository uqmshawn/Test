"""MQTT broker implementation for handling communication between local and remote clients."""

import logging
import os
import tempfile
import ssl
import threading
import time
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

import paho.mqtt.client as mqtt  # pylint: disable=import-error
from paho.mqtt.packettypes import PacketTypes  # pylint: disable=import-error
from paho.mqtt.properties import Properties  # pylint: disable=import-error

from logger_setup import set_process_name
from models import Message, Certificate, SessionLocal, DeviceData, OutboundDeviceData
from mqtt_utils import connect_mqtt_client
from settings_util import load_settings
from device_util import extract_measures, are_measures_different

set_process_name("mqtt_broker")


class Configuration:
    """
    Singleton class to manage configuration settings for the MQTT broker.
    Attributes:
        iot_env (str): IoT environment name.
        tenant_name (str): Tenant name.
        device_name (str): Device name.
        aws_iot_endpoint (str): AWS IoT endpoint.
    Methods:
        get_instance() -> Configuration:
            Returns the singleton instance of the Configuration class.
        _values_changed(settings: Dict[str, str]) -> bool:
            Checks if any configuration values have changed.
        has_required_values(settings: Dict[str, str]) -> bool:
            Checks if all required configuration values are present and non-empty.
        update_from_settings(settings: Dict[str, str]) -> bool:
            Updates configuration from settings dict. Returns True if values changed.
    """

    _instance: Optional["Configuration"] = None

    def __init__(self) -> None:
        if Configuration._instance is not None:
            raise RuntimeError("Use Configuration.get_instance() instead")
        self.iot_env: str = ""
        self.tenant_name: str = ""
        self.device_name: str = ""
        self.aws_iot_endpoint: str = ""
        Configuration._instance = self

    @classmethod
    def get_instance(cls: Type["Configuration"]) -> "Configuration":
        if cls._instance is None:
            cls._instance = Configuration()
        return cls._instance

    def _values_changed(self, settings: Dict[str, str]) -> bool:
        """Check if any configuration values have changed."""
        new_iot_env = settings.get("iot_environment", "").strip()
        new_tenant = settings.get("tenant_name", "").strip()
        new_device = settings.get("device_name", "").strip()
        new_endpoint = settings.get("aws_iot_endpoint", "").strip()
        return (
            new_iot_env != self.iot_env
            or new_tenant != self.tenant_name
            or new_device != self.device_name
            or new_endpoint != self.aws_iot_endpoint
        )

    def has_required_values(self, settings: Dict[str, str]) -> bool:
        """Check if all required configuration values are present and non-empty."""
        new_iot_env = settings.get("iot_environment", "").strip()
        new_tenant = settings.get("tenant_name", "").strip()
        new_device = settings.get("device_name", "").strip()
        new_endpoint = settings.get("aws_iot_endpoint", "").strip()
        return bool(all([new_iot_env, new_tenant, new_device, new_endpoint]))

    def update_from_settings(self, settings: Dict[str, str]) -> bool:
        """Update configuration from settings dict. Returns True if values changed."""
        if not self.has_required_values(settings):
            return False

        if not self._values_changed(settings):
            return False

        # Update values if all checks pass
        self.iot_env = settings.get("iot_environment", "").strip()
        self.tenant_name = settings.get("tenant_name", "").strip()
        self.device_name = settings.get("device_name", "").strip()
        self.aws_iot_endpoint = settings.get("aws_iot_endpoint", "").strip()
        logging.info("Configuration updated from database settings")
        return True


CONFIG = Configuration.get_instance()


class CertificateManager:
    """
    Manages SSL/TLS certificates for MQTT connections from database.
    """

    def __init__(self) -> None:
        self.required_certs: List[str] = ["ca.pem", "cert.crt", "private.key"]
        self._cert_data: Dict[str, bytes] = {}

    def wait_for_certs(self) -> None:
        """Wait for all required certificates to become available in the database."""
        while True:
            missing = self._get_missing_certs()
            if not missing:
                self._load_cert_data()
                logging.info("Certificates are configured.")
                break

            status_message = (
                f"Missing certificates: {', '.join(missing)}. Retrying in 10 seconds..."
            )
            logging.error(status_message)
            time.sleep(10)

    def _get_missing_certs(self) -> List[str]:
        """Get list of missing certificate files from database."""
        with SessionLocal() as db_session:
            existing_certs = {
                cert.filename: cert.content
                for cert in db_session.query(Certificate)
                .filter(Certificate.filename.in_(self.required_certs))
                .all()
            }
        return [cert for cert in self.required_certs if cert not in existing_certs]

    def _load_cert_data(self) -> None:
        """Load certificate data from database."""
        with SessionLocal() as db_session:
            certs = (
                db_session.query(Certificate)
                .filter(Certificate.filename.in_(self.required_certs))
                .all()
            )
            for cert in certs:
                self._cert_data[cert.filename] = cert.content

    def _write_temp_cert(self, filename: str) -> str:
        """Write certificate data to a temporary file and return its path."""

        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, filename)

        with open(temp_path, "wb") as f:
            f.write(self._cert_data[filename])

        return temp_path

    def configure_client(self, client: mqtt.Client) -> None:
        """Configure TLS settings for an MQTT client using temporary certificate files."""
        ca_cert_path = self._write_temp_cert("ca.pem")
        cert_file_path = self._write_temp_cert("cert.crt")
        key_file_path = self._write_temp_cert("private.key")

        client.tls_set(
            ca_certs=ca_cert_path,
            certfile=cert_file_path,
            keyfile=key_file_path,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLSv1_2,
            ciphers=None,
        )


def attempt_reconnect(
    client: mqtt.Client, max_retries: int = 3, retry_delay: int = 3
) -> bool:
    """
    Attempt to reconnect the MQTT client with a two-stage approach.

    First tries a simple reconnect, and if that fails, attempts a full reconnection
    with proper cleanup and setup. Uses exponential backoff between attempts.

    Args:
        client: The MQTT client to reconnect
        max_retries: Maximum number of reconnection attempts per stage (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 3)

    Returns:
        bool: True if reconnection was successful, False otherwise
    """
    # Track reconnection history to detect unstable connections
    if not hasattr(client, "_reconnect_history"):
        client._reconnect_history = []  # type: ignore

    # Add current timestamp to reconnection history
    current_time = time.time()
    client._reconnect_history.append(current_time)  # type: ignore

    # Only keep the last 10 reconnection attempts
    if len(client._reconnect_history) > 10:  # type: ignore
        client._reconnect_history = client._reconnect_history[-10:]  # type: ignore

    # Check if we're in an unstable connection state (multiple reconnects in short period)
    is_unstable = False
    if len(client._reconnect_history) >= 3:  # type: ignore
        # If we have 3+ reconnects in the last 10 seconds, consider it unstable
        first_timestamp = client._reconnect_history[0]  # type: ignore
        if current_time - first_timestamp < 10 and len(client._reconnect_history) >= 3:  # type: ignore
            is_unstable = True
            logging.warning(
                "Detected unstable connection: %d reconnect attempts in the last %.2f seconds",
                len(client._reconnect_history),  # type: ignore
                current_time - first_timestamp,
            )

    if not client.is_connected():
        logging.warning("Client disconnected, attempting to reconnect...")

        # Adjust backoff strategy based on connection stability
        initial_backoff = retry_delay
        if is_unstable:
            # Use a longer initial backoff for unstable connections
            initial_backoff = max(10, retry_delay * 3)
            logging.info("Using extended backoff strategy due to unstable connection")

        # Stage 1: Try simple reconnect with exponential backoff
        backoff_delay = initial_backoff
        max_backoff = (
            60 if is_unstable else 30
        )  # Longer max backoff for unstable connections

        for attempt in range(1, max_retries + 1):
            try:
                result = client.reconnect()
                if result == mqtt.MQTT_ERR_SUCCESS:
                    logging.info(
                        "Successfully reconnected to MQTT broker (simple reconnect)."
                    )
                    # Add a small delay after successful reconnection to prevent immediate disconnect detection
                    # This helps with unstable connections that rapidly disconnect after reconnecting
                    if is_unstable:
                        time.sleep(1)
                    return True

                logging.error(
                    "Simple reconnect attempt %d/%d failed with error code %s. Retrying in %d seconds...",
                    attempt,
                    max_retries,
                    result,
                    backoff_delay,
                )
            except Exception as reconnect_err:
                logging.error(
                    "Error during simple reconnection attempt %d/%d: %s. Retrying in %d seconds...",
                    attempt,
                    max_retries,
                    reconnect_err,
                    backoff_delay,
                )

            # Wait before next attempt
            time.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, max_backoff)

        # If we reach here, simple reconnect failed - Stage 2: Try full reconnection
        logging.info("Simple reconnection failed, attempting full reconnection...")

        # Reset backoff for stage 2, but keep it higher for unstable connections
        backoff_delay = initial_backoff

        for attempt in range(1, max_retries + 1):
            try:
                # For AWS IoT connections, a full reconnect might be needed
                # Get the current broker address and port from client
                host = getattr(client, "_host", CONFIG.aws_iot_endpoint)
                port = getattr(client, "_port", 8883)

                # Stop the network loop and disconnect cleanly
                client.loop_stop()
                try:
                    client.disconnect()
                except Exception:
                    pass  # Already disconnected

                # For unstable connections, add a delay before reconnecting
                if is_unstable:
                    time.sleep(2)

                # Reconnect with full connection parameters
                # Use clean_start=True to ensure a fresh session
                result = client.connect(host, port, keepalive=60, clean_start=True)

                if result == mqtt.MQTT_ERR_SUCCESS:
                    # Restart the network loop
                    client.loop_start()
                    logging.info(
                        "Full reconnection to MQTT broker successful (attempt %d/%d)",
                        attempt,
                        max_retries,
                    )
                    # Add a small delay after successful reconnection
                    if is_unstable:
                        time.sleep(1)
                    return True

                logging.error(
                    "Full reconnect attempt %d/%d failed with code %s. Retrying in %d seconds...",
                    attempt,
                    max_retries,
                    result,
                    backoff_delay,
                )
            except Exception as full_reconnect_err:
                logging.error(
                    "Error during full reconnection attempt %d/%d: %s. Retrying in %d seconds...",
                    attempt,
                    max_retries,
                    full_reconnect_err,
                    backoff_delay,
                )

            # Wait before next attempt
            time.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, max_backoff)

        # If we reach here, both reconnection approaches failed
        logging.error(
            "Failed to reconnect after %d simple reconnect attempts and %d full reconnect attempts.",
            max_retries,
            max_retries,
        )

    return False


def process_single_message(client: mqtt.Client, msg: Message, _session: Any) -> None:
    """Process a single unsent message."""
    props = Properties(PacketTypes.PUBLISH)
    props.UserProperty = [("ID", str(msg.id))]
    result = client.publish(msg.topic, msg.payload, qos=1, properties=props)

    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        msg.sent_on = datetime.now(timezone.utc)
        msg.last_error = None
        logging.info("Resent message id %s successfully.", msg.id)
    else:
        msg.last_error = f"Publish failed with code {result.rc}"
        logging.error(
            "Publish failed for message id %s with code %s", msg.id, result.rc
        )


def process_batch_messages(client: mqtt.Client) -> None:
    """Process all unsent messages in the database."""
    session = SessionLocal()
    try:
        unsent = session.query(Message).filter(Message.sent_on.is_(None)).all()
        if unsent:
            logging.info("Processing queued messages: %d", len(unsent))
            for msg in unsent:
                process_single_message(client, msg, session)
            session.commit()
    except Exception as batch_err:
        logging.error("Error processing unsent messages: %s", batch_err)
        session.rollback()
    finally:
        session.close()


def process_unsent_messages(client: mqtt.Client) -> None:
    """
    Main loop for processing unsent messages with continuous reconnection attempts.

    This function runs in its own thread and continuously checks for unsent messages,
    attempting to reconnect if disconnected using a progressive backoff strategy.
    """
    backoff_delay = 5  # Start with 5 seconds
    max_backoff = 900  # Maximum backoff of 15 minutes

    # Track consecutive reconnection failures
    consecutive_failures = 0
    max_consecutive_failures = 5

    # Track last successful connection time
    last_successful_connection = 0

    while True:
        if client:
            if not client.is_connected():
                current_time = time.time()

                # Check if we've had a successful connection recently
                connection_unstable = False
                if last_successful_connection > 0:
                    # If we were connected in the last 10 seconds and now disconnected again
                    if current_time - last_successful_connection < 10:
                        connection_unstable = True
                        logging.warning(
                            "Connection appears unstable - disconnected after only %.2f seconds",
                            current_time - last_successful_connection,
                        )

                # First attempt a reconnect using the attempt_reconnect function
                if not attempt_reconnect(client):
                    consecutive_failures += 1

                    # Adjust backoff based on consecutive failures
                    if consecutive_failures > max_consecutive_failures:
                        # Use a more aggressive backoff for persistent failures
                        logging.warning(
                            "Detected %d consecutive reconnection failures, using extended backoff",
                            consecutive_failures,
                        )
                        backoff_delay = min(backoff_delay * 2, max_backoff)

                    logging.info(
                        "Initial reconnect attempts failed. Continuing with backoff strategy... "
                        "Will retry in %d seconds (consecutive failures: %d).",
                        backoff_delay,
                        consecutive_failures,
                    )
                    # Wait using current backoff delay
                    time.sleep(backoff_delay)

                    # Increase backoff delay with a gentler curve than the disconnect handlers
                    # since this function runs continuously
                    if backoff_delay < 60:
                        backoff_delay = min(backoff_delay * 1.5, max_backoff)
                    else:
                        backoff_delay = min(backoff_delay * 1.2, max_backoff)

                    continue
                else:
                    # Record successful connection time
                    last_successful_connection = time.time()

                    # Reset consecutive failures counter
                    consecutive_failures = 0

                    # Reset backoff delay on successful reconnection, but use a higher
                    # initial value if the connection seems unstable
                    if connection_unstable:
                        backoff_delay = (
                            15  # Start with a higher backoff for unstable connections
                        )
                    else:
                        backoff_delay = 5

            if client.is_connected():
                # Process any unsent messages
                process_batch_messages(client)
                # Use a shorter sleep when connected and processing normally
                time.sleep(30)

        else:
            # Something is wrong with the client object itself
            logging.error("MQTT client is invalid. Waiting before retry...")
            time.sleep(60)


def on_remote_disconnect(
    client: mqtt.Client,
    _userdata: Any,
    disconnect_flags: int,
    reason_code: int,
    _properties: Optional[Properties] = None,
) -> None:
    """
    Handle disconnection from remote MQTT broker with infinite retry strategy.
    Uses exponential backoff that increases to a maximum of 30 minutes between attempts.
    """
    logging.error(
        "Remote MQTT broker disconnected with flags %s, reason_code %s. Reconnecting...",
        disconnect_flags,
        reason_code,
    )

    attempt = 0
    backoff_delay = 5  # Start with 5 seconds
    max_backoff = 1800  # Maximum backoff of 30 minutes

    # Infinite retry loop - will keep trying until successful or process is killed
    while True:
        result = client.reconnect()
        if result == mqtt.MQTT_ERR_SUCCESS:
            logging.info(
                "Reconnected to AWS MQTT broker after %d attempts.", attempt + 1
            )
            return

        attempt += 1

        # Calculate backoff with dampened exponential growth (slower than doubling each time)
        # For longer backoffs, grow more slowly to avoid reaching maximum too quickly
        if backoff_delay < 60:  # Under 1 minute, double
            backoff_delay = min(backoff_delay * 2, max_backoff)
        elif backoff_delay < 300:  # Under 5 minutes, increase by 50%
            backoff_delay = min(backoff_delay * 1.5, max_backoff)
        else:  # Over 5 minutes, increase by 20%
            backoff_delay = min(backoff_delay * 1.2, max_backoff)

        # Log less frequently as attempts increase to avoid flooding logs
        if attempt <= 10 or attempt % 10 == 0 or backoff_delay == max_backoff:
            logging.error(
                "Reconnect attempt %d failed with error code %s. Retrying in %d seconds...",
                attempt,
                result,
                backoff_delay,
            )

        time.sleep(backoff_delay)


def on_local_disconnect(
    client: mqtt.Client,
    _userdata: Any,
    disconnect_flags: int,
    reason_code: int,
    _properties: Optional[Properties] = None,
) -> None:
    """
    Handle disconnection from local MQTT broker with infinite retry strategy.
    Uses exponential backoff that increases more gradually than remote broker
    since local broker connectivity is critical and typically faster to recover.
    """
    logging.error(
        "Local MQTT broker disconnected with flags %s, reason_code %s. Reconnecting...",
        disconnect_flags,
        reason_code,
    )

    attempt = 0
    backoff_delay = 2  # Start with 2 seconds for local broker
    max_backoff = 600  # Maximum backoff of 10 minutes (shorter than remote since local)

    # Infinite retry loop - will keep trying until successful or process is killed
    while True:
        result = client.reconnect()
        if result == mqtt.MQTT_ERR_SUCCESS:
            logging.info(
                "Reconnected to local MQTT broker after %d attempts.", attempt + 1
            )
            return

        attempt += 1

        # Calculate backoff with gentler exponential growth for local broker
        # Local broker should recover faster, so use more aggressive retry pattern
        if backoff_delay < 30:  # Under 30 seconds, increase by 50%
            backoff_delay = min(backoff_delay * 1.5, max_backoff)
        else:  # Over 30 seconds, increase by 30%
            backoff_delay = min(backoff_delay * 1.3, max_backoff)

        # Log less frequently as attempts increase to avoid flooding logs
        if attempt <= 20 or attempt % 20 == 0 or backoff_delay == max_backoff:
            logging.error(
                "Local reconnect attempt %d failed with error code %s. Retrying in %d seconds...",
                attempt,
                result,
                backoff_delay,
            )

        time.sleep(backoff_delay)


def remote_on_message(
    _client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
) -> None:
    topic = message.topic
    payload = message.payload.decode("utf-8")
    logging.info("Remote message received on topic '%s': %s", topic, payload)

    # Route the message to mosquitto: if topic contains "/in/", take substring from "in/" onwards.
    if userdata is None or not hasattr(userdata, "publish_local_message"):
        raise ValueError("Userdata must implement the publish_local_message method")

    if "/in/" in topic:
        local_topic = "in/" + topic.split("/in/", 1)[1]
        userdata.publish_local_message(local_topic, payload)
    else:
        logging.warning(
            "Invalid topic format %s; message not routed to local broker.", topic
        )


AWS_MQTT_LOG_MSG = "AWS MQTT: %s"


def aws_on_log(_client: mqtt.Client, _userdata: Any, level: int, buf: str) -> None:
    if level == mqtt.MQTT_LOG_DEBUG:
        logging.debug(AWS_MQTT_LOG_MSG, buf)
    elif level == mqtt.MQTT_LOG_WARNING:
        logging.warning(AWS_MQTT_LOG_MSG, buf)
    elif level == mqtt.MQTT_LOG_ERR:
        logging.error(AWS_MQTT_LOG_MSG, buf)
    else:
        logging.info(AWS_MQTT_LOG_MSG, buf)


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    _flags: Dict[str, Any],
    _reason_code: int,
    _properties: Properties,
) -> None:
    inbound_topic = f"{CONFIG.iot_env}/{CONFIG.tenant_name}/{CONFIG.device_name}/in/#"
    logging.info("Attempting to subscribe with configuration:")
    logging.info("  iot_env: %s", CONFIG.iot_env)
    logging.info("  tenant_name: %s", CONFIG.tenant_name)
    logging.info("  device_name: %s", CONFIG.device_name)
    logging.info("  full topic: %s", inbound_topic)

    client.subscribe(inbound_topic)
    logging.info("Subscribed to inbound topic '%s' via on_connect.", inbound_topic)

    status_topic = (
        f"{CONFIG.iot_env}/{CONFIG.tenant_name}/{CONFIG.device_name}/out/status"
    )
    if userdata is None or not hasattr(userdata, "publish_remote_message"):
        raise ValueError("Userdata must implement the publish_remote_message method")
    userdata.publish_remote_message(
        status_topic, '{"message": "MQTT Broker connected via MQTT v5."}'
    )


def process_device_message(_source: str, payload: str) -> bool:
    """
    Process and store device message, determine if it should be forwarded.

    NOTE: we may need to make this more robust, if there is a case that the MQTT broker is down,
    then maybe it needs to batch these up and send them when it comes back up.
    So it may need to check multiple records, not just the last one sent. But that needs more thought.

    Returns:
        bool: True if message should be forwarded, False otherwise
    """
    try:
        device_data = json.loads(payload)
        now = datetime.now(timezone.utc)
        measures = extract_measures(device_data)

        with SessionLocal() as session:
            # Store the new device data
            new_data = DeviceData(timestamp=now, payload=device_data, measures=measures)
            session.add(new_data)

            # Get the last sent data to compare
            last_outbound = (
                session.query(OutboundDeviceData)
                .order_by(OutboundDeviceData.last_sent.desc())
                .first()
            )

            should_send = True
            if last_outbound:
                last_measures = last_outbound.payload.get("measures")
                result = are_measures_different(measures, last_measures)
                if result.is_different:
                    should_send = True
                    logging.info("Measures are different because:")
                    for reason in result.reasons:
                        logging.info("- %s", reason)
                else:
                    should_send = False
                    logging.info("Measures are the same")

            if should_send:
                # Store the outbound record
                new_outbound = OutboundDeviceData(
                    last_sent=now, payload={"measures": measures}
                )
                session.add(new_outbound)

            session.commit()
            return should_send

    except Exception as device_err:
        logging.error("Error processing device message: %s", device_err)
        return True  # On error, forward the message to be safe


def on_local_message(
    _client_local: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
) -> None:
    source = message.topic
    outbound_topic = (
        f"{CONFIG.iot_env}/{CONFIG.tenant_name}/{CONFIG.device_name}/{source}"
    )

    # Handle device messages specially
    if source == "out/device":
        should_forward = process_device_message(source, message.payload.decode("utf-8"))
        if not should_forward:
            logging.info("Device message not forwarded due to no significant changes")
            return

    logging.info(
        "Routing local message from '%s' to outbound topic '%s'.",
        message.topic,
        outbound_topic,
    )
    if userdata is None or not hasattr(userdata, "publish_remote_message"):
        raise ValueError("Userdata must implement the publish_remote_message method")
    userdata.publish_remote_message(outbound_topic, message.payload.decode("utf-8"))


class MQTTClient:
    """Base class for MQTT client management."""

    def __init__(self, client_id: str, is_remote: bool = False) -> None:
        # Add a unique suffix to the client_id to prevent conflicts
        unique_client_id = f"{client_id}_{str(uuid.uuid4())[:8]}"
        logging.info("Initializing MQTT client with ID: %s", unique_client_id)

        self.client: Optional[mqtt.Client] = mqtt.Client(
            client_id=unique_client_id, protocol=mqtt.MQTTv5
        )
        self.is_remote = is_remote

    def disconnect(self) -> None:
        """Safely disconnect the client."""
        try:
            if self.client:
                self.client.loop_stop()
                self.client.on_disconnect = None
                self.client.disconnect()
                logging.info(
                    "%s MQTT client disconnected.",
                    "Remote" if self.is_remote else "Local",
                )
        except Exception as disconnect_err:
            logging.error(
                "Failed to disconnect %s client: %s",
                "remote" if self.is_remote else "local",
                disconnect_err,
            )


class RemoteClient(MQTTClient):
    """Handles remote MQTT client setup and management."""

    def __init__(self, config: Configuration, cert_manager: CertificateManager) -> None:
        client_id = f"{config.tenant_name}_{config.device_name}_mqtt_broker"
        super().__init__(client_id, is_remote=True)
        self.config = config
        self.cert_manager = cert_manager

    def setup(self) -> None:
        """Configure the remote client."""
        self.cert_manager.configure_client(self.client)
        logging.info("Remote client configured with certificates.")
        if self.client is not None:
            self.client.on_disconnect = on_remote_disconnect  # type: ignore
            self.client.on_log = aws_on_log
            self.client.enable_logger()
            self.client.on_message = remote_on_message
            self.client.on_connect = on_connect  # type: ignore
        else:
            raise ValueError("Remote MQTT client not initialized for setup")

    def connect(self) -> None:
        """Connect to the remote broker."""
        connect_mqtt_client(self.client, self.config.aws_iot_endpoint, 8883)
        self._start_message_processor()

    def _start_message_processor(self) -> None:
        """Start the unsent messages processing thread."""
        unsent_thread = threading.Thread(
            target=process_unsent_messages, args=(self.client,), daemon=True
        )
        unsent_thread.start()


class LocalClient(MQTTClient):
    """Handles local MQTT client setup and management."""

    def __init__(self) -> None:
        super().__init__("local_broker")

    def setup(self) -> None:
        """Configure the local client."""
        if self.client is not None:
            self.client.on_disconnect = on_local_disconnect  # type: ignore
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)
            self.client.on_message = on_local_message
        else:
            raise ValueError("Local MQTT client not initialized for setup")

    def connect(self) -> None:
        """Connect to the local broker."""
        broker_addr = os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto")
        connect_mqtt_client(self.client, broker_addr, 1883)
        if self.client is not None:
            self.client.subscribe("out/#")
            logging.info("Subscribed to local topic 'out/#'.")
        else:
            raise ValueError("Local MQTT client not initialized for connect")


class BrokerManager:
    """Manages MQTT broker connections and lifecycle."""

    def __init__(self) -> None:
        self.cert_manager = CertificateManager()
        self.remote_client: Optional[RemoteClient] = None
        self.local_client: Optional[LocalClient] = None

    def initialize(self) -> None:
        """Initialize certificates and configuration."""
        self.cert_manager.wait_for_certs()
        self._wait_for_config()

    def _wait_for_config(self) -> None:
        """Wait for valid configuration."""
        while True:
            settings = load_settings()
            CONFIG.update_from_settings(settings)
            if CONFIG.has_required_values(settings):

                logging.info("Configuration loaded successfully.")
                break

            logging.error("Missing configuration values. Waiting for valid config...")
            time.sleep(10)

    def setup_clients(self) -> None:
        """Set up both MQTT clients."""
        self.remote_client = RemoteClient(CONFIG, self.cert_manager)
        self.local_client = LocalClient()

        self.remote_client.setup()
        self.local_client.setup()
        if self.remote_client.client is not None:
            self.remote_client.client.user_data_set(self)
        if self.local_client.client is not None:
            self.local_client.client.user_data_set(self)

    def connect_clients(self) -> None:
        """Connect both clients in parallel."""
        if self.remote_client is None:
            raise ValueError("Remote client not initialized for connection.")

        if self.local_client is None:
            raise ValueError("Local client not initialized for connection.")

        remote_thread = threading.Thread(target=self.remote_client.connect)
        local_thread = threading.Thread(target=self.local_client.connect)
        remote_thread.start()
        local_thread.start()
        remote_thread.join()
        local_thread.join()

    def start_config_monitor(self) -> None:
        """Start the configuration monitoring thread."""
        monitor_thread = threading.Thread(target=self._monitor_config, daemon=True)
        monitor_thread.start()
        logging.info("Started monitor config thread.")

    def _monitor_config(self) -> None:
        """Monitor for configuration changes."""
        while True:
            time.sleep(30)
            new_settings = load_settings()
            if CONFIG.update_from_settings(new_settings):
                logging.info(
                    "Configuration change detected, reconnecting remote MQTT client."
                )
                if self.remote_client:
                    self.remote_client.disconnect()
                    self.remote_client = RemoteClient(CONFIG, self.cert_manager)
                    self.remote_client.setup()
                    if self.remote_client.client:
                        self.remote_client.client.user_data_set(self)
                        logging.info(
                            "Reconnecting remote client with new configuration %s",
                            CONFIG,
                        )
                    self.remote_client.connect()
                else:
                    raise ValueError("Remote client not initialized for reconnection.")

    def disconnect_clients(self) -> None:
        """Disconnect both clients safely."""
        if self.remote_client:
            self.remote_client.disconnect()
        if self.local_client:
            self.local_client.disconnect()

    def publish_remote_message(self, topic: str, payload: str) -> None:
        """Publish a message to the remote broker."""
        if not self.remote_client:
            logging.warning("Remote client not initialized; message discarded.")
            return

        logging.info("Publishing message to topic '%s': %s", topic, payload)
        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            # Create a new message record (queued unsent by default)
            msg = Message(
                timestamp=now,
                topic=topic,
                payload=payload,
                sent_on=None,
                last_error=None,
            )
            session.add(msg)
            session.commit()
            message_id = msg.id
        except Exception as db_err:
            logging.error("Error inserting message into DB: %s", db_err)
            session.rollback()
            session.close()
            return

        if not (self.remote_client.client and self.remote_client.client.is_connected()):
            logging.warning("Client not connected; message queued in database.")
            session.close()
            return

        try:
            props = Properties(PacketTypes.PUBLISH)
            props.UserProperty = [("ID", str(message_id))]
            result = self.remote_client.client.publish(
                topic, payload, qos=1, properties=props
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                msg.sent_on = datetime.now(timezone.utc)
                msg.last_error = None
                logging.info("Published message id %s successfully.", message_id)
            else:
                msg.last_error = f"Publish failed with code {result.rc}"
                logging.error(
                    "Publish failed for message id %s with code %s",
                    message_id,
                    result.rc,
                )
            session.commit()
        except Exception as publish_err:
            logging.error("Error updating message id %s: %s", message_id, publish_err)
            session.rollback()
        finally:
            session.close()

    def publish_local_message(self, topic: str, payload: str) -> None:
        """Publish a message to the local (mosquitto) broker."""
        if not self.local_client:
            logging.warning("Local client not initialized; cannot publish message.")
            return
        if self.local_client.client and self.local_client.client.is_connected():
            logging.info("Publishing local message to topic '%s': %s", topic, payload)
            self.local_client.client.publish(topic, payload, qos=1)
        else:
            logging.warning("Local client not connected; cannot publish message.")


def run_mqtt_broker() -> None:
    """Main broker function with reduced complexity."""
    broker = BrokerManager()
    try:
        broker.initialize()
        broker.setup_clients()
        broker.connect_clients()
        broker.start_config_monitor()

        # Keep process alive
        while True:
            time.sleep(1)
    except Exception as broker_err:
        logging.error("Error in MQTT Broker: %s", broker_err)
        broker.disconnect_clients()
        raise


# Outer loop to keep the broker always running
if __name__ == "__main__":
    while True:
        try:
            run_mqtt_broker()
        except Exception as main_err:
            logging.error(
                "MQTT Broker failed with error: %s. Restarting in 10 seconds...",
                main_err,
            )
            time.sleep(10)

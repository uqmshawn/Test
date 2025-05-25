"""Utility functions for MQTT client connections and operations."""

import time
import logging
import socket
from typing import Dict, Any
import paho.mqtt.client as mqtt  # pylint: disable=import-error

# Import settings_util here to avoid circular imports
from settings_util import load_settings


def _calculate_backoff_delay(
    current_delay: float, max_delay: float, factor: float = 1.5
) -> float:
    """Calculate the next backoff delay using exponential backoff.

    Args:
        current_delay: Current delay in seconds
        max_delay: Maximum delay in seconds
        factor: Multiplier for the backoff (default: 1.5)

    Returns:
        float: The new backoff delay, capped at max_delay
    """
    return min(current_delay * factor, max_delay)


def connect_mqtt_client(
    client: mqtt.Client,
    broker_address: str,
    port: int,
    max_retries: int = 3,
    retry_delay: int = 5,
    keepalive: int = 60,
    stability_delay: float = 2.0,
) -> bool:
    """Connect MQTT client with retry logic.

    Args:
        client: The MQTT client to connect
        broker_address: The broker address to connect to
        port: The port to connect on
        max_retries: Maximum number of connection attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 5)
        keepalive: Keepalive interval in seconds (default: 60)
        stability_delay: Delay in seconds to verify connection stability (default: 2.0)

    Returns:
        bool: True if connection was successful, False otherwise
    """
    # Configure client with more robust settings
    # Set a shorter keepalive for local Docker environment to detect disconnects faster
    if broker_address in ["localhost", "127.0.0.1", "mosquitto"]:
        # For local connections, use a shorter keepalive to detect disconnects faster
        actual_keepalive = 15
    else:
        actual_keepalive = keepalive

    # Set socket options for more reliable connections
    client.socket_options = (
        # TCP Keepalive: Enable TCP keepalive
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    )

    # Configure reconnect behavior
    # Set min_delay=1 to start with a 1 second delay
    # Set max_delay=60 to cap the delay at 60 seconds
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    attempt = 0
    backoff_delay = retry_delay
    max_backoff = 30  # Maximum backoff of 30 seconds

    while max_retries < 0 or attempt < max_retries:
        try:
            # Use clean_start=True to ensure a fresh session each time
            # This prevents issues with stale sessions and client ID conflicts
            result = client.connect(
                broker_address, port, keepalive=actual_keepalive, clean_start=True
            )

            if result == mqtt.MQTT_ERR_SUCCESS:
                # Start the network loop in a background thread
                client.loop_start()

                # Add a configurable delay to ensure the connection is stable
                logging.info(
                    "Connection successful, waiting %s seconds to verify stability...",
                    stability_delay,
                )
                time.sleep(
                    stability_delay
                )  # Configurable delay to verify connection stability

                # Double-check that we're still connected after the delay
                if client.is_connected():
                    # Try a simple ping to verify the connection is working
                    try:
                        # Determine if this is a local or remote connection
                        is_aws_connection = broker_address not in [
                            "localhost",
                            "127.0.0.1",
                            "mosquitto",
                        ]

                        if is_aws_connection:
                            # For AWS connections, use a topic that's already configured in your AWS IoT policy
                            # Load settings from the database to get the proper environment, tenant, and device
                            settings = load_settings()

                            if settings and all(
                                k in settings
                                for k in [
                                    "iot_environment",
                                    "tenant_name",
                                    "device_name",
                                ]
                            ):
                                # Use the same topic structure as the status topic in mqtt_broker.py
                                env = settings["iot_environment"]
                                tenant = settings["tenant_name"]
                                device = settings["device_name"]

                                # Construct a status topic using the proper environment
                                status_topic = f"{env}/{tenant}/{device}/out/status"
                                test_result = client.publish(
                                    status_topic,
                                    '{"message": "Connection test"}',
                                    qos=0,
                                )
                                logging.info(
                                    f"Published connection test to topic: {status_topic}"
                                )
                            else:
                                # Fallback if settings are not available
                                logging.warning(
                                    "Could not load settings for connection test, using fallback topic"
                                )
                                test_result = client.publish(
                                    "connection/test", "test", qos=0
                                )
                        else:
                            # For local connections, use a simple test topic
                            test_result = client.publish(
                                "connection/test", "test", qos=0
                            )
                        if test_result.rc == mqtt.MQTT_ERR_SUCCESS:
                            logging.info(
                                "Connected to MQTT broker at %s:%s (keepalive: %d seconds)",
                                broker_address,
                                port,
                                actual_keepalive,
                            )
                            # Wait a bit more to ensure everything is stable
                            time.sleep(1.0)
                            return True
                        else:
                            logging.warning(
                                "Connection test publish failed with code %s",
                                test_result.rc,
                            )
                    except Exception as test_err:
                        logging.warning(
                            "Connection test failed: %s",
                            test_err,
                        )

                # If we get here, either the connection test failed or we're not connected
                logging.warning(
                    "Connection to MQTT broker at %s:%s was initially successful but failed stability check",
                    broker_address,
                    port,
                )

            # If we get here, either the initial connection failed or we disconnected immediately
            if max_retries >= 0:
                if attempt < max_retries - 1:  # Don't sleep on last attempt
                    logging.error(
                        "Failed to connect (error code %s) to MQTT broker. Attempt %d/%d. Retrying in %d seconds...",
                        result,
                        attempt + 1,
                        max_retries,
                        backoff_delay,
                    )
                    time.sleep(backoff_delay)
                    # Use exponential backoff
                    backoff_delay = _calculate_backoff_delay(backoff_delay, max_backoff)
                else:
                    logging.error(
                        "Failed to connect (error code %s) to MQTT broker after %d attempts.",
                        result,
                        max_retries,
                    )
            else:
                logging.error(
                    "Failed to connect (error code %s) to MQTT broker. Attempt %d. Retrying in %d seconds...",
                    result,
                    attempt + 1,
                    backoff_delay,
                )
                time.sleep(backoff_delay)
                # Use exponential backoff
                backoff_delay = _calculate_backoff_delay(backoff_delay, max_backoff)

        except Exception as connect_err:
            logging.error(
                "Exception during connection attempt %d: %s. Retrying in %d seconds...",
                attempt + 1,
                connect_err,
                backoff_delay,
            )
            time.sleep(backoff_delay)
            # Use exponential backoff
            backoff_delay = _calculate_backoff_delay(backoff_delay, max_backoff)

        attempt += 1

    return False

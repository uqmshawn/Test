"""Utility functions for MQTT client connections and operations."""

import time
import logging
import socket
import paho.mqtt.client as mqtt  # pylint: disable=import-error


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
) -> bool:
    """Connect MQTT client with retry logic.

    Args:
        client: The MQTT client to connect
        broker_address: The broker address to connect to
        port: The port to connect on
        max_retries: Maximum number of connection attempts (default: 3). Use -1 for infinite retries.
        retry_delay: Delay between retries in seconds (default: 5)
        keepalive: Keepalive interval in seconds (default: 60)

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

                # Add a small delay to ensure the connection is stable
                time.sleep(0.5)

                # Double-check that we're still connected after the delay
                if client.is_connected():
                    logging.info(
                        "Connected to MQTT broker at %s:%s (keepalive: %d seconds)",
                        broker_address,
                        port,
                        actual_keepalive,
                    )
                    return True
                else:
                    logging.warning(
                        "Connection to MQTT broker at %s:%s was initially successful but disconnected immediately",
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

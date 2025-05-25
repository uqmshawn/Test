"""
Mock vehicle data generator for development and testing.

This module provides functionality to generate mock vehicle data
for use in development and testing environments when real vehicle hardware
is not available or practical to use.
"""

import time
import logging
import threading
from typing import Dict, Any, Optional, List

from models import VehicleData, SessionLocal
import vehicle_data_utils as vdu
from timestamp_util import get_utc_now


def start_mock_vehicle_generator() -> threading.Thread:
    """Start the mock vehicle data generator thread.

    Returns:
        threading.Thread: The started mock vehicle generator thread
    """
    mock_thread = threading.Thread(
        target=mock_vehicle_generator, daemon=True, name="mock_vehicle_thread"
    )
    mock_thread.start()
    logging.info("Started mock vehicle generator thread")
    return mock_thread


def mock_vehicle_generator() -> None:
    """Generate mock vehicle data with ignition on/off events.

    This function simulates a vehicle with:
    1. Initial state: ignition ON (ign_state=True)
    2. After ~60 seconds: ignition OFF (ign_state=False)
    3. No further changes after that
    """
    # Initial state - both inputs enabled, ignition ON
    initial_data = {
        "ign_enabled": True,
        "ign_state": True,
        "io_enabled": True,
        "io_state": False,
    }

    # Store the initial state
    stored_data = vdu.store_vehicle_data(initial_data)
    if stored_data:
        vdu.log_new_vehicle_data(initial_data)
        logging.info("Mock vehicle: Initial state - Ignition ON")
        logging.debug(
            "Mock vehicle: Stored initial vehicle data with ID %s", stored_data.id
        )
    else:
        logging.error("Mock vehicle: Failed to store initial vehicle data")

    # Wait approximately 60 seconds
    time.sleep(60)

    # Update to ignition OFF
    updated_data = {
        "ign_enabled": True,
        "ign_state": False,
        "io_enabled": True,
        "io_state": False,
    }

    # Store the updated state
    stored_data = vdu.store_vehicle_data(updated_data)
    if stored_data:
        vdu.log_new_vehicle_data(updated_data)
        logging.info("Mock vehicle: Updated state - Ignition OFF")
        logging.debug(
            "Mock vehicle: Stored updated vehicle data with ID %s", stored_data.id
        )
    else:
        logging.error("Mock vehicle: Failed to store updated vehicle data")

    # Keep the thread alive but don't make any more changes
    while True:
        time.sleep(60)

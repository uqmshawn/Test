"""
Mock GPS data generator for development and testing.

This module provides functionality to generate realistic mock GPS data
for use in development and testing environments when real GPS hardware
is not available or practical to use.
"""

import time
import logging
import random
import math
import threading
from typing import Optional

from data_access import store_gps_coordinates, GPSCoordinates
from location_util import SPEED_THRESHOLD, ACCURACY_THRESHOLD, BASE_DISTANCE_THRESHOLD
from timestamp_util import get_mqtt_timestamp


def start_mock_gps_generator() -> threading.Thread:
    """Start the mock GPS generator thread.

    Returns:
        threading.Thread: The started mock GPS generator thread
    """
    mock_thread = threading.Thread(
        target=mock_gps_generator, daemon=True, name="mock_gps_thread"
    )
    mock_thread.start()
    logging.info("Started mock GPS generator thread")
    return mock_thread


def mock_gps_generator() -> None:
    """Generate mock GPS data periodically with significant changes to trigger AWS messages."""
    # Base coordinates (Gold Coast, Queensland, Australia)
    base_lat = -28.0167
    base_lng = 153.4000

    # Add a random offset to the base coordinates (within ~5km)
    # 0.05 degrees is approximately 5km at this latitude
    random_lat_offset = random.uniform(-0.05, 0.05)
    random_lng_offset = random.uniform(-0.05, 0.05)

    # Apply the random offset to create a new base location for this session
    session_base_lat = base_lat + random_lat_offset
    session_base_lng = base_lng + random_lng_offset

    logging.info(
        "Mock GPS: Using random starting location near Gold Coast at (%s, %s)",
        session_base_lat,
        session_base_lng,
    )

    # Track current values to ensure significant changes
    current_lat = session_base_lat
    current_lng = session_base_lng
    current_speed = 0.0
    current_pdop = 1.0

    # Simulate a vehicle moving in a circular pattern around the Gold Coast area
    angle = 0.0
    radius = 0.005  # Roughly 500 meters at this latitude to simulate more movement

    while True:
        try:
            # Decide which parameter to change significantly
            change_type = random.choice(["location", "speed", "accuracy"])

            if change_type == "location":
                # Move in a circular pattern to ensure distance change exceeds threshold
                angle += random.uniform(
                    0.2, 0.5
                )  # Increment angle for circular movement
                # Calculate new position that will be at least 10m away (exceeding BASE_DISTANCE_THRESHOLD)
                new_lat = session_base_lat + radius * math.sin(angle)
                new_lng = session_base_lng + radius * math.cos(angle)

                # Keep speed and accuracy relatively stable
                new_speed = current_speed + random.uniform(-0.1, 0.1)
                new_pdop = current_pdop

                logging.info("Mock GPS: Significant location change")

            elif change_type == "speed":
                # Keep location relatively stable
                new_lat = current_lat + random.uniform(-0.00001, 0.00001)
                new_lng = current_lng + random.uniform(-0.00001, 0.00001)

                # Make a significant speed change (at least SPEED_THRESHOLD)
                new_speed = current_speed + (
                    SPEED_THRESHOLD * 2 * (1 if random.random() > 0.5 else -1)
                )
                new_speed = max(0, new_speed)  # Ensure speed is not negative
                new_pdop = current_pdop

                logging.info("Mock GPS: Significant speed change")

            else:  # accuracy change
                # Keep location relatively stable
                new_lat = current_lat + random.uniform(-0.00001, 0.00001)
                new_lng = current_lng + random.uniform(-0.00001, 0.00001)

                # Keep speed relatively stable
                new_speed = current_speed + random.uniform(-0.1, 0.1)

                # Make a significant accuracy (PDOP) change
                new_pdop = current_pdop + (
                    ACCURACY_THRESHOLD * 1.2 * (1 if random.random() > 0.5 else -1)
                )
                new_pdop = max(1.0, min(10.0, new_pdop))  # Keep PDOP between 1 and 10

                logging.info("Mock GPS: Significant accuracy change")

            # Update current values
            current_lat = new_lat
            current_lng = new_lng
            current_speed = new_speed
            current_pdop = new_pdop

            # Generate mock GPS data with the new values
            mock_gps = GPSCoordinates(
                lat=current_lat,
                lng=current_lng,
                alt=10.0 + random.uniform(-2.0, 2.0),  # Small altitude variations
                spd=current_speed,
                heading=random.uniform(0, 360),  # Random heading
                pdop=current_pdop,
                hdop=current_pdop * 0.8,  # Typically HDOP is lower than PDOP
                vdop=current_pdop * 0.6,  # Typically VDOP is lower than PDOP
                loc_ts=get_mqtt_timestamp(),  # Use our MQTT timestamp utility (seconds since epoch)
            )

            store_gps_coordinates(mock_gps)
            logging.info(
                "Stored mock GPS coordinates: (%s, %s, alt=%s, spd=%s, pdop=%s)",
                mock_gps.lat,
                mock_gps.lng,
                mock_gps.alt,
                mock_gps.spd,
                mock_gps.pdop,
            )

            # Sleep for about a minute between significant changes
            sleep_time = random.uniform(50, 70)  # 50-70 seconds
            logging.info(f"Mock GPS: Next update in {sleep_time:.1f} seconds")
            time.sleep(sleep_time)

        except Exception as mock_err:
            logging.error("Error generating mock GPS data: %s", mock_err)
            time.sleep(5)

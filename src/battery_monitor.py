"""Battery monitoring module that manages power modes based on battery level.

This module monitors battery levels from the BMS and controls system power modes
to optimize power consumption based on the battery state of charge.
"""

import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

import paho.mqtt.client as mqtt
from sqlalchemy import desc

from models import SessionLocal, BMSData
from mqtt_utils import connect_mqtt_client
import logger_setup

# Setup logging
logger_setup.set_process_name("battery_monitor")

# Power mode thresholds (percentage)
THRESHOLDS = {
    "normal": 75,  # Above this percentage, normal mode is active
    "eco": 50,  # Above this percentage, eco mode is active
    "critical": 25,  # Above this percentage, critical mode is active
    # Below critical threshold, emergency mode is active
}

# Hysteresis value to prevent mode oscillation (percentage)
HYSTERESIS = 5

# Define components affected by each power mode
COMPONENT_STATES = {
    "normal": {
        "communication": {
            "enabled": True,
            "update_interval": 60,
        },  # Full updates every minute
        "freezer": {"enabled": True, "temperature": -18},  # Normal freezer temp
        "water_pump": {"enabled": True, "power": 100},  # 100% power
        "lighting": {"enabled": True, "brightness": 100},  # 100% brightness
        "climate_control": {"enabled": True, "temperature": 22, "fan_speed": "high"},
        "navigation": {"enabled": True, "detail_level": "high"},
        "entertainment": {"enabled": True},
    },
    "eco": {
        "communication": {
            "enabled": True,
            "update_interval": 120,
        },  # Updates every 2 minutes
        "freezer": {"enabled": True, "temperature": -16},  # Slightly higher temp
        "water_pump": {"enabled": True, "power": 80},  # 80% power
        "lighting": {"enabled": True, "brightness": 60},  # 60% brightness
        "climate_control": {"enabled": True, "temperature": 24, "fan_speed": "low"},
        "navigation": {"enabled": True, "detail_level": "medium"},
        "entertainment": {"enabled": False},
    },
    "critical": {
        "communication": {
            "enabled": True,
            "update_interval": 300,
        },  # Updates every 5 minutes
        "freezer": {"enabled": True, "temperature": -15},  # Minimum safe temp
        "water_pump": {"enabled": True, "power": 60},  # 60% power
        "lighting": {"enabled": False},  # Lighting off
        "climate_control": {"enabled": False},  # Climate off
        "navigation": {"enabled": True, "detail_level": "low"},
        "entertainment": {"enabled": False},
    },
    "emergency": {
        "communication": {
            "enabled": True,
            "update_interval": 600,
        },  # Updates every 10 minutes
        "freezer": {"enabled": True, "temperature": -15},  # Minimum safe temp
        "water_pump": {"enabled": False},  # Water pump off
        "lighting": {"enabled": False},  # Lighting off
        "climate_control": {"enabled": False},  # Climate off
        "navigation": {"enabled": False},  # Navigation off
        "entertainment": {"enabled": False},  # Entertainment off
    },
}


def start_battery_monitor_thread(
    mqtt_broker_address: str = "mosquitto", mqtt_broker_port: int = 1883
) -> threading.Thread:
    """Start the battery monitor in a separate thread.

    Args:
        mqtt_broker_address: Address of the MQTT broker
        mqtt_broker_port: Port of the MQTT broker

    Returns:
        threading.Thread: The started battery monitor thread
    """

    def run_monitor():
        try:
            logging.info("Starting battery monitoring service")
            monitor = BatteryMonitor(
                mqtt_broker_address=mqtt_broker_address,
                mqtt_broker_port=mqtt_broker_port,
            )
            monitor.run()
        except Exception as e:
            logging.error(f"Error in battery monitor: {e}")

    thread = threading.Thread(
        target=run_monitor, daemon=True, name="battery_monitor_thread"
    )
    thread.start()
    logging.info("Started battery monitoring thread for power mode management")
    return thread


class BatteryMonitor:
    """Monitors battery levels and manages power modes."""

    def __init__(
        self, mqtt_broker_address: str = "mosquitto", mqtt_broker_port: int = 1883
    ):
        """Initialize the battery monitor.

        Args:
            mqtt_broker_address: Address of the MQTT broker
            mqtt_broker_port: Port of the MQTT broker
        """
        self.mqtt_broker_address = mqtt_broker_address
        self.mqtt_broker_port = mqtt_broker_port
        self.current_mode: str = "unknown"
        self.battery_level: int = 0
        self.current_threshold: int = 0
        self.thresholds = THRESHOLDS.copy()
        self.hysteresis = HYSTERESIS
        self.mqtt_client = None
        self.last_mode_change = datetime.now(timezone.utc)
        self.mode_stabilized = False

    def get_latest_battery_level(self) -> Optional[int]:
        """Get the latest battery level from the database.

        Returns:
            Integer battery level or None if no data available
        """
        with SessionLocal() as session:
            latest_bms = (
                session.query(BMSData).order_by(desc(BMSData.timestamp)).first()
            )
            if latest_bms:
                # Use integer_soc if available, otherwise fallback to state_of_charge as integer
                if latest_bms.integer_soc is not None:
                    return latest_bms.integer_soc
                return int(latest_bms.state_of_charge)
        return None

    def determine_power_mode(self, battery_level: int) -> str:
        """Determine the appropriate power mode based on battery level.

        This function includes hysteresis to prevent oscillation between modes.

        Args:
            battery_level: Current battery level (0-100%)

        Returns:
            The power mode: 'normal', 'eco', 'critical', or 'emergency'
        """
        current_mode = self.current_mode

        # If we don't know the current mode, determine it based on simple thresholds
        if current_mode == "unknown":
            if battery_level >= self.thresholds["normal"]:
                return "normal"
            elif battery_level >= self.thresholds["eco"]:
                return "eco"
            elif battery_level >= self.thresholds["critical"]:
                return "critical"
            else:
                return "emergency"

        # Apply hysteresis to prevent mode oscillation
        if current_mode == "normal":
            # Only go down to eco if we fall below (normal threshold - hysteresis)
            if battery_level < (self.thresholds["normal"] - self.hysteresis):
                return "eco"
            return "normal"

        elif current_mode == "eco":
            # Go up to normal if we rise above normal threshold
            if battery_level >= self.thresholds["normal"]:
                return "normal"
            # Go down to critical if we fall below (eco threshold - hysteresis)
            elif battery_level < (self.thresholds["eco"] - self.hysteresis):
                return "critical"
            return "eco"

        elif current_mode == "critical":
            # Go up to eco if we rise above eco threshold
            if battery_level >= self.thresholds["eco"]:
                return "eco"
            # Go down to emergency if we fall below (critical threshold - hysteresis)
            elif battery_level < (self.thresholds["critical"] - self.hysteresis):
                return "emergency"
            return "critical"

        elif current_mode == "emergency":
            # Go up to critical if we rise above critical threshold
            if battery_level >= self.thresholds["critical"]:
                return "critical"
            return "emergency"

        return current_mode

    def connect_mqtt(self) -> bool:
        """Connect to the MQTT broker.

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            if self.mqtt_client is None:
                self.mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5)

            if not self.mqtt_client.is_connected():
                # Use the connect_mqtt_client utility function from mqtt_utils
                connected = connect_mqtt_client(
                    self.mqtt_client, self.mqtt_broker_address, self.mqtt_broker_port
                )

                if connected:
                    # Subscribe to configuration updates
                    self.mqtt_client.subscribe("system/power_config", qos=1)
                    # Set up callbacks
                    self.mqtt_client.on_message = self.on_message
                    return True
                else:
                    logging.error(
                        "Failed to connect to MQTT broker using connect_mqtt_client utility"
                    )
                    return False

            return True
        except Exception as e:
            logging.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages.

        Args:
            client: MQTT client
            userdata: User data
            msg: MQTT message
        """
        try:
            if msg.topic == "system/power_config":
                payload = json.loads(msg.payload.decode())
                logging.info(f"Received power configuration update: {payload}")

                # Extract and validate thresholds
                if "thresholds" in payload:
                    thresholds = payload["thresholds"]
                    if all(k in thresholds for k in ["normal", "eco", "critical"]):
                        # Ensure thresholds are in descending order
                        if (
                            thresholds["normal"]
                            > thresholds["eco"]
                            > thresholds["critical"]
                            >= 0
                        ):
                            self.thresholds = {
                                "normal": thresholds["normal"],
                                "eco": thresholds["eco"],
                                "critical": thresholds["critical"],
                            }
                            logging.info(f"Updated power thresholds: {self.thresholds}")
                        else:
                            logging.warning(
                                "Invalid threshold values (not in descending order)"
                            )
                    else:
                        logging.warning("Incomplete threshold configuration")

                # Extract and validate hysteresis
                if "hysteresis" in payload:
                    hysteresis = payload["hysteresis"]
                    if 0 <= hysteresis <= 20:
                        self.hysteresis = hysteresis
                        logging.info(f"Updated hysteresis: {self.hysteresis}")
                    else:
                        logging.warning(f"Invalid hysteresis value: {hysteresis}")

        except json.JSONDecodeError:
            logging.error("Failed to parse power config message")
        except Exception as e:
            logging.error(f"Error handling MQTT message: {e}")

    def publish_power_mode(self, mode: str, battery_level: int) -> None:
        """Publish current power mode to MQTT.

        Args:
            mode: Current power mode
            battery_level: Current battery level
        """
        if not self.connect_mqtt():
            logging.error("Failed to connect to MQTT broker, cannot publish power mode")
            return

        try:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "battery_level": battery_level,
                "components": COMPONENT_STATES[mode],
            }

            # Publish to retained topic for system components to reference
            self.mqtt_client.publish(
                "system/power_mode", json.dumps(payload), qos=1, retain=True
            )
            logging.info(f"Published power mode: {mode} (battery: {battery_level}%)")

        except Exception as e:
            logging.error(f"Failed to publish power mode: {e}")

    def run(self, polling_interval: int = 30) -> None:
        """Run the battery monitor continuously.

        Args:
            polling_interval: Seconds between battery level checks
        """
        logging.info(
            f"Starting battery monitor with polling interval: {polling_interval}s"
        )
        logging.info(
            f"Initial thresholds: {self.thresholds}, hysteresis: {self.hysteresis}"
        )

        # Ensure MQTT connection
        self.connect_mqtt()

        while True:
            try:
                # Get latest battery level
                battery_level = self.get_latest_battery_level()

                if battery_level is not None:
                    self.battery_level = battery_level

                    # Determine appropriate power mode
                    new_mode = self.determine_power_mode(battery_level)

                    # Handle mode change if needed
                    if new_mode != self.current_mode:
                        logging.info(
                            f"Power mode change: {self.current_mode} -> {new_mode} (battery: {battery_level}%)"
                        )
                        self.current_mode = new_mode
                        self.last_mode_change = datetime.now(timezone.utc)
                        self.mode_stabilized = False

                        # Publish the new power mode
                        self.publish_power_mode(new_mode, battery_level)
                    elif not self.mode_stabilized:
                        # Stabilize the mode after 5 minutes in the same mode
                        time_since_change = (
                            datetime.now(timezone.utc) - self.last_mode_change
                        ).total_seconds()
                        if time_since_change > 300:  # 5 minutes
                            logging.info(
                                f"Power mode {self.current_mode} is now stabilized"
                            )
                            self.mode_stabilized = True
                            self.publish_power_mode(self.current_mode, battery_level)

                # Periodic update (once per hour) even if mode hasn't changed
                if (
                    datetime.now(timezone.utc).minute == 0
                    and datetime.now(timezone.utc).second < polling_interval
                ):
                    logging.info(
                        f"Hourly update: power mode {self.current_mode}, battery level {self.battery_level}%"
                    )
                    if self.current_mode != "unknown":
                        self.publish_power_mode(self.current_mode, self.battery_level)

            except Exception as e:
                logging.error(f"Error in battery monitor: {e}")

            # Sleep until next check
            time.sleep(polling_interval)


def main() -> None:
    """Main entry point for the battery monitor."""
    # Initialize and run the battery monitor
    monitor = BatteryMonitor()
    monitor.run()


if __name__ == "__main__":
    main()

"""Utilities for working with vehicle data from the Peplink router."""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

import requests
from models import VehicleData, SessionLocal
from router_utils import re_authenticate


def fetch_router_vehicle_data(
    session: requests.Session, router_ip: str, credentials: dict[str, str]
) -> tuple[requests.Session, Optional[Dict[str, Any]]]:
    """
    Fetch vehicle data from the router API (GPIO input status).

    Returns a tuple of (session, data) where session may be a new session
    if re-authentication was required, and data may be None if the request failed.
    """
    # Use the endpoint for GPIO input status
    endpoint = f"https://{router_ip}/api/status.gpio.input?list"
    vehicle_data = None

    # Function to handle API request with optional re-authentication
    def make_api_request(
        current_session: requests.Session,
    ) -> tuple[requests.Session, Optional[requests.Response]]:
        """Make API request and handle authentication if needed."""
        try:
            resp = current_session.get(endpoint, verify=False)
            # Need to re-authenticate?
            if resp.status_code == 401:
                try:
                    current_session = re_authenticate(router_ip, credentials)
                    resp = current_session.get(endpoint, verify=False)
                except Exception as auth_err:
                    logging.error("Authentication failed: %s", auth_err)
                    return current_session, None

            # Check if we got a valid response
            if resp.status_code != 200:
                logging.error(
                    "Failed to fetch vehicle data, status code: %s",
                    resp.status_code,
                )
                return current_session, None

            return current_session, resp
        except Exception as req_err:
            logging.error("Request error: %s", req_err)
            return current_session, None

    def parse_and_validate_response(
        response: requests.Response,
    ) -> Optional[Dict[str, Any]]:
        """Parse response JSON and validate API response status."""
        try:
            data = response.json()
            logging.debug("Vehicle data API response: %s", data)

            if str(data.get("stat", "")).lower() != "ok":
                error_code = data.get("code", "unknown")
                error_msg = data.get("message", "No message")

                if error_code == 401 and error_msg == "Unauthorized":
                    # Signal that re-authentication is needed
                    return None

                logging.error("API error: %s", data)
                return None

            # Valid response
            return data
        except Exception as parse_err:
            logging.error("Failed to parse API response: %s", parse_err)
            return None

    def handle_auth_failure(
        error_response: dict,
    ) -> tuple[requests.Session, Optional[Dict[str, Any]]]:
        """Handle authentication failure by re-authenticating."""
        if error_response.get("code") != 401:
            return session, None

        try:
            new_session = re_authenticate(router_ip, credentials)
            new_session, new_response = make_api_request(new_session)
            if not new_response:
                return new_session, None

            new_data = parse_and_validate_response(new_response)
            if new_data:
                return new_session, new_data
        except Exception as auth_err:
            logging.error("Re-authentication failed: %s", auth_err)

        return session, None

    try:
        session, response = make_api_request(session)
        if not response:
            return session, None

        vehicle_data = parse_and_validate_response(response)

        if vehicle_data is None:
            try:
                error_response = response.json()
                session, vehicle_data = handle_auth_failure(error_response)
            except Exception as json_err:
                logging.error("Failed to parse error response: %s", json_err)
    except Exception as general_err:
        logging.exception("Unexpected error: %s", general_err)

    return session, vehicle_data


def parse_vehicle_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse the vehicle data response and extract GPIO input status.

    Returns a dictionary with the parsed data or None if parsing fails.
    """
    if not data or data.get("stat") != "ok" or "response" not in data:
        return None

    try:
        response = data["response"]
        return _process_gpio_data(response)
    except Exception as parse_err:
        logging.error("Failed to parse vehicle data: %s", parse_err)
        return None


def _process_gpio_data(response: Dict[str, Any]) -> Dict[str, Any]:
    """Process GPIO data from response and return formatted result.

    Handles cases where only some GPIO inputs are present in the response.
    Missing inputs will have their state set to None, but won't affect
    change detection for inputs that are present.
    """
    # Initialize with default values - use None instead of False for state
    # so we can distinguish between "off" (False) and "not present" (None)
    result = {
        "ign_enabled": False,
        "ign_state": None,
        "io_enabled": False,
        "io_state": None,
    }

    _extract_input_data(response, result)
    return result


def _extract_input_data(response: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Extract input data from response and update the result dictionary.

    Only updates values for GPIO inputs that are present in the response.
    Missing inputs retain their default values set in _process_gpio_data.
    """
    for input_id, input_data in response.items():
        if input_id == "order":
            continue

        if input_data.get("name") == "IGN I/P":
            # Convert enable to boolean, ensure we capture changes between true/false
            result["ign_enabled"] = bool(input_data.get("enable", False))
            # Only set state if it exists in input_data, otherwise leave as None
            if "state" in input_data:
                result["ign_state"] = bool(input_data["state"])

        elif input_data.get("name") == "I/O":
            result["io_enabled"] = bool(input_data.get("enable", False))
            if "state" in input_data:
                result["io_state"] = bool(input_data["state"])


def store_vehicle_data(vehicle_data: Dict[str, Any]) -> Optional[VehicleData]:
    """Store vehicle data in the database."""
    try:
        with SessionLocal() as session:
            now = datetime.now(timezone.utc)

            new_record = VehicleData(
                timestamp=now,
                ign_enabled=vehicle_data["ign_enabled"],
                ign_state=vehicle_data["ign_state"],
                io_enabled=vehicle_data["io_enabled"],
                io_state=vehicle_data["io_state"],
            )

            session.add(new_record)
            session.commit()
            session.refresh(new_record)

            logging.debug("Stored vehicle data: %s", vehicle_data)
            return new_record
    except Exception as db_err:
        logging.error("Failed to store vehicle data: %s", db_err)
        return None


def should_store_vehicle_data(
    current_data: Dict[str, Any], last_data: Optional[Dict[str, Any]]
) -> bool:
    """Determine if vehicle data should be stored based on changes.

    Checks each input separately and only compares values that are present
    in both current and last data. An input being missing (None) is treated
    as different from being present with any state (0/1).
    """
    if last_data is None:
        return True

    def has_input_changed(input_prefix: str) -> bool:
        """Check if a specific input has changed, considering None as different from 0/1."""
        enabled_key = f"{input_prefix}_enabled"
        state_key = f"{input_prefix}_state"

        # Always check enabled status as it should always be present as true/false
        if current_data[enabled_key] != last_data[enabled_key]:
            logging.debug(
                "Enabled state changed for %s: %s -> %s",
                input_prefix,
                last_data[enabled_key],
                current_data[enabled_key],
            )
            return True

        # For state, None is treated as different from 0/1
        current_state = current_data[state_key]
        last_state = last_data[state_key]

        # If one is None and the other isn't, that's a change
        if (current_state is None) != (last_state is None):
            logging.debug(
                "State presence changed for %s: %s -> %s",
                input_prefix,
                last_state,
                current_state,
            )
            return True

        # If both are not None, compare their values
        if current_state is not None and last_state is not None:
            if current_state != last_state:
                logging.debug(
                    "State value changed for %s: %s -> %s",
                    input_prefix,
                    last_state,
                    current_state,
                )
                return True

        return False

    # Check each input separately
    ign_changed = has_input_changed("ign")
    io_changed = has_input_changed("io")

    if ign_changed or io_changed:
        logging.debug(
            "Vehicle data changed - Current: %s, Last: %s", current_data, last_data
        )

    return ign_changed or io_changed


def log_new_vehicle_data(vehicle_data: Dict[str, Any]) -> None:
    """Log the new vehicle data in a consistent format."""

    def format_state(enabled: bool, state: Optional[bool], _name: str) -> str:
        """Format the state of an input, handling missing values."""
        if not enabled:
            return "Disabled"
        if state is None:
            return "Not Present"
        return "On" if state else "Off"

    logging.info(
        "Stored new vehicle data: IGN=%s, IO=%s",
        format_state(vehicle_data["ign_enabled"], vehicle_data["ign_state"], "IGN"),
        format_state(vehicle_data["io_enabled"], vehicle_data["io_state"], "I/O"),
    )


def create_vehicle_payload(record: VehicleData) -> Dict[str, Any]:
    """Convert a VehicleData record to a dictionary format for MQTT payload.

    Property names are in camelCase and abbreviated for smaller payload size.

    Mapping:
    - timestamp -> ts
    - ign_enabled -> ignEn
    - ign_state -> ignSt
    - io_enabled -> ioEn
    - io_state -> ioSt
    """
    return {
        "ts": int(record.timestamp.timestamp() * 1000),  # Convert to ms
        "ignEn": record.ign_enabled,
        "ignSt": record.ign_state,
        "ioEn": record.io_enabled,
        "ioSt": record.io_state,
    }


def detect_vehicle_data_changes(
    records: List[VehicleData], last_data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Detect changes in vehicle data and return records that have changes."""
    if not records:
        return []

    # Always include the first record if there's no previous data
    if not last_data:
        return [create_vehicle_payload(records[-1])]

    changes = []
    previous = last_data

    # Compare each record against the previous one
    for record in records:
        current = create_vehicle_payload(record)
        changed = False

        # Compare enabled states and actual states
        if (
            current["ignEn"] != previous["ignEn"]
            or current["ioEn"] != previous["ioEn"]
            or current["ignSt"] != previous["ignSt"]
            or current["ioSt"] != previous["ioSt"]
        ):

            logging.debug(
                "Vehicle data change detected - Previous: %s, Current: %s",
                previous,
                current,
            )
            changed = True

        if changed:
            changes.append(current)
            previous = current

    return changes

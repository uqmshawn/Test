"""
Timestamp utility module for consistent timestamp handling across the application.

This module provides functions for creating, formatting, and converting timestamps
in various formats (UTC datetime, epoch seconds, epoch milliseconds, ISO format, etc.)
to ensure consistency throughout the application.

Standardized timestamp conventions:
- For MQTT messages, timestamps are always in seconds since epoch (integer)
- The field name "ts" always refers to seconds since epoch
- If millisecond precision is needed, use "tsMs" as the field name
"""

import logging
from datetime import datetime, timezone
from typing import Union, Optional

# Standard format for UTC timestamps in logs and UI
UTC_TIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def get_utc_now() -> datetime:
    """
    Get current UTC datetime with timezone information.

    This is the preferred method for getting the current time in the application.

    Returns:
        datetime: Current UTC datetime with timezone information
    """
    return datetime.now(timezone.utc)


def format_datetime_utc(dt: datetime) -> str:
    """
    Format a datetime object as a UTC timestamp string.

    Args:
        dt: The datetime object to format

    Returns:
        str: Formatted UTC timestamp string (e.g., "2023-01-01 12:34:56 UTC")
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime(UTC_TIME_FORMAT)


def get_current_timestamp_utc() -> str:
    """
    Get current UTC timestamp as a formatted string.

    Returns:
        str: Current UTC timestamp string (e.g., "2023-01-01 12:34:56 UTC")
    """
    return format_datetime_utc(get_utc_now())


def datetime_to_epoch_seconds(dt: datetime) -> int:
    """
    Convert a datetime object to Unix epoch seconds.

    Args:
        dt: The datetime object to convert

    Returns:
        int: Unix epoch timestamp in seconds
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def datetime_to_epoch_milliseconds(dt: datetime) -> int:
    """
    Convert a datetime object to Unix epoch milliseconds.

    Args:
        dt: The datetime object to convert

    Returns:
        int: Unix epoch timestamp in milliseconds
    """
    return int(datetime_to_epoch_seconds(dt) * 1000)


def epoch_seconds_to_datetime(epoch_seconds: Union[int, float]) -> datetime:
    """
    Convert Unix epoch seconds to a datetime object.

    Args:
        epoch_seconds: Unix epoch timestamp in seconds

    Returns:
        datetime: Datetime object with UTC timezone
    """
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)


def epoch_milliseconds_to_datetime(epoch_ms: Union[int, float]) -> datetime:
    """
    Convert Unix epoch milliseconds to a datetime object.

    Args:
        epoch_ms: Unix epoch timestamp in milliseconds

    Returns:
        datetime: Datetime object with UTC timezone
    """
    return epoch_seconds_to_datetime(epoch_ms / 1000)


def datetime_to_iso_format(dt: datetime) -> str:
    """
    Convert a datetime object to ISO 8601 format.

    Args:
        dt: The datetime object to convert

    Returns:
        str: ISO 8601 formatted timestamp (e.g., "2023-01-01T12:34:56+00:00")
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def get_current_timestamp_iso() -> str:
    """
    Get current UTC timestamp in ISO 8601 format.

    Returns:
        str: Current UTC timestamp in ISO 8601 format
    """
    return datetime_to_iso_format(get_utc_now())


def parse_iso_timestamp(iso_timestamp: str) -> Optional[datetime]:
    """
    Parse an ISO 8601 formatted timestamp string into a datetime object.

    Args:
        iso_timestamp: ISO 8601 formatted timestamp string

    Returns:
        Optional[datetime]: Parsed datetime object with UTC timezone, or None if parsing fails
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        # Ensure timezone is UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def get_current_epoch_seconds() -> int:
    """
    Get current UTC time as Unix epoch seconds.

    Returns:
        int: Current UTC time as Unix epoch seconds
    """
    return datetime_to_epoch_seconds(get_utc_now())


def get_current_epoch_milliseconds() -> int:
    """
    Get current UTC time as Unix epoch milliseconds.

    Returns:
        int: Current UTC time as Unix epoch milliseconds
    """
    return datetime_to_epoch_milliseconds(get_utc_now())


# MQTT-specific timestamp functions


def get_mqtt_timestamp() -> int:
    """
    Get current UTC time as Unix epoch seconds for MQTT messages.

    Following the standardized convention:
    - MQTT message timestamps use field name "ts"
    - "ts" is always in seconds since epoch (integer)

    Returns:
        int: Current UTC time as Unix epoch seconds
    """
    return get_current_epoch_seconds()


def ensure_mqtt_timestamp(timestamp: Union[int, float, datetime, str, None]) -> int:
    """
    Ensure a timestamp is in the correct format for MQTT messages (seconds since epoch).

    Args:
        timestamp: A timestamp in any supported format (epoch seconds, epoch milliseconds,
                  datetime object, ISO format string, or None)

    Returns:
        int: Timestamp converted to seconds since epoch

    If timestamp is:
    - None: returns current time in seconds since epoch
    - datetime: converts to seconds since epoch
    - str: parses as ISO format string and converts to seconds since epoch
    - int/float < 10000000000: assumed to be seconds since epoch already
    - int/float >= 10000000000: assumed to be milliseconds since epoch, converted to seconds
    """
    if timestamp is None:
        return get_mqtt_timestamp()

    if isinstance(timestamp, datetime):
        return datetime_to_epoch_seconds(timestamp)

    # Handle ISO format string timestamps
    if isinstance(timestamp, str):
        try:
            dt = parse_iso_timestamp(timestamp)
            if dt:
                return datetime_to_epoch_seconds(dt)
            # If parsing fails, try to convert directly to int
            return int(timestamp)
        except ValueError:
            # If all parsing fails, return current time
            logging.warning(
                f"Could not parse timestamp string: {timestamp}, using current time"
            )
            return get_mqtt_timestamp()

    # If it's a large number (13 digits), it's likely milliseconds since epoch
    if isinstance(timestamp, (int, float)) and timestamp >= 10000000000:
        return int(timestamp / 1000)

    # Otherwise assume it's already seconds since epoch
    return int(timestamp)

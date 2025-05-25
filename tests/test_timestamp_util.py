"""Tests for timestamp_util.py functions."""

import pytest
from datetime import datetime, timezone, timedelta
from freezegun import freeze_time

from src.timestamp_util import (
    get_utc_now,
    format_datetime_utc,
    get_current_timestamp_utc,
    datetime_to_epoch_seconds,
    datetime_to_epoch_milliseconds,
    epoch_seconds_to_datetime,
    epoch_milliseconds_to_datetime,
    datetime_to_iso_format,
    get_current_timestamp_iso,
    parse_iso_timestamp,
    get_current_epoch_seconds,
    get_current_epoch_milliseconds,
    get_mqtt_timestamp,
    ensure_mqtt_timestamp,
)


def test_get_utc_now():
    """Test that get_utc_now returns a timezone-aware datetime."""
    dt = get_utc_now()
    assert dt.tzinfo is not None
    assert dt.tzinfo == timezone.utc


def test_format_datetime_utc():
    """Test formatting a datetime as UTC string."""
    # Test with timezone-aware datetime
    dt = datetime(2023, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    formatted = format_datetime_utc(dt)
    assert formatted == "2023-01-01 12:34:56 UTC"

    # Test with naive datetime (should be treated as UTC)
    naive_dt = datetime(2023, 1, 1, 12, 34, 56)
    formatted = format_datetime_utc(naive_dt)
    assert formatted == "2023-01-01 12:34:56 UTC"


@freeze_time("2023-01-01 12:34:56", tz_offset=0)
def test_get_current_timestamp_utc():
    """Test getting current timestamp as UTC string."""
    timestamp = get_current_timestamp_utc()
    assert timestamp == "2023-01-01 12:34:56 UTC"


def test_datetime_to_epoch_seconds():
    """Test converting datetime to epoch seconds."""
    dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    epoch = datetime_to_epoch_seconds(dt)
    # 2023-01-01 12:00:00 UTC in epoch seconds
    expected = 1672574400
    assert epoch == expected

    # Test with naive datetime
    naive_dt = datetime(2023, 1, 1, 12, 0, 0)
    epoch = datetime_to_epoch_seconds(naive_dt)
    assert epoch == expected


def test_datetime_to_epoch_milliseconds():
    """Test converting datetime to epoch milliseconds."""
    dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    epoch_ms = datetime_to_epoch_milliseconds(dt)
    # 2023-01-01 12:00:00 UTC in epoch milliseconds
    expected = 1672574400000
    assert epoch_ms == expected


def test_epoch_seconds_to_datetime():
    """Test converting epoch seconds to datetime."""
    epoch = 1672574400  # 2023-01-01 12:00:00 UTC
    dt = epoch_seconds_to_datetime(epoch)
    expected = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert dt == expected


def test_epoch_milliseconds_to_datetime():
    """Test converting epoch milliseconds to datetime."""
    epoch_ms = 1672574400000  # 2023-01-01 12:00:00 UTC
    dt = epoch_milliseconds_to_datetime(epoch_ms)
    expected = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert dt == expected


def test_datetime_to_iso_format():
    """Test converting datetime to ISO format."""
    dt = datetime(2023, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    iso = datetime_to_iso_format(dt)
    assert iso == "2023-01-01T12:34:56+00:00"

    # Test with naive datetime
    naive_dt = datetime(2023, 1, 1, 12, 34, 56)
    iso = datetime_to_iso_format(naive_dt)
    assert iso == "2023-01-01T12:34:56+00:00"


@freeze_time("2023-01-01 12:34:56", tz_offset=0)
def test_get_current_timestamp_iso():
    """Test getting current timestamp in ISO format."""
    iso = get_current_timestamp_iso()
    assert iso == "2023-01-01T12:34:56+00:00"


def test_parse_iso_timestamp():
    """Test parsing ISO timestamp."""
    iso = "2023-01-01T12:34:56+00:00"
    dt = parse_iso_timestamp(iso)
    expected = datetime(2023, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    assert dt == expected

    # Test with invalid format
    invalid = "not-a-timestamp"
    assert parse_iso_timestamp(invalid) is None


@freeze_time("2023-01-01 12:34:56", tz_offset=0)
def test_get_current_epoch_seconds():
    """Test getting current time as epoch seconds."""
    epoch = get_current_epoch_seconds()
    # 2023-01-01 12:34:56 UTC in epoch seconds
    expected = 1672576496
    assert epoch == expected


@freeze_time("2023-01-01 12:34:56", tz_offset=0)
def test_get_current_epoch_milliseconds():
    """Test getting current time as epoch milliseconds."""
    epoch_ms = get_current_epoch_milliseconds()
    # 2023-01-01 12:34:56 UTC in epoch milliseconds
    expected = 1672576496000
    assert epoch_ms == expected


@freeze_time("2023-01-01 12:34:56", tz_offset=0)
def test_get_mqtt_timestamp():
    """Test getting current time as MQTT timestamp (seconds since epoch)."""
    ts = get_mqtt_timestamp()
    # 2023-01-01 12:34:56 UTC in epoch seconds
    expected = 1672576496
    assert ts == expected
    assert isinstance(ts, int)


def test_ensure_mqtt_timestamp():
    """Test ensuring various timestamp formats are converted to seconds since epoch."""
    # Test with None (should return current time)
    with freeze_time("2023-01-01 12:34:56", tz_offset=0):
        ts = ensure_mqtt_timestamp(None)
        assert ts == 1672576496
        assert isinstance(ts, int)

    # Test with datetime
    dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = ensure_mqtt_timestamp(dt)
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with seconds since epoch
    ts = ensure_mqtt_timestamp(1672574400)
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with milliseconds since epoch
    ts = ensure_mqtt_timestamp(1672574400000)
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with float seconds
    ts = ensure_mqtt_timestamp(1672574400.123)
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with float milliseconds
    ts = ensure_mqtt_timestamp(1672574400123.456)
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with ISO format string
    ts = ensure_mqtt_timestamp("2023-01-01T12:00:00+00:00")
    assert ts == 1672574400
    assert isinstance(ts, int)

    # Test with ISO format string with microseconds
    ts = ensure_mqtt_timestamp("2023-01-01T12:00:00.123456+00:00")
    assert ts == 1672574400
    assert isinstance(ts, int)

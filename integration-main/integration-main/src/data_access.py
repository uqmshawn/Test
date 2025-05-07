"""Data access functions for the application."""

from datetime import datetime, timedelta, timezone
import logging
from typing import NamedTuple

from sqlalchemy.exc import SQLAlchemyError
from models import (
    SessionLocal,
    Message,
    GPSData,
    OutboundGPSData,
    DeviceData,
    OutboundDeviceData,
)

UTC_TIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


class GPSCoordinates(NamedTuple):
    """Encapsulates all GPS parameters required for storing GPS data."""

    lat: float
    lng: float
    alt: float
    spd: float
    heading: float
    pdop: float
    hdop: float
    vdop: float
    loc_ts: int


def _is_valid_gps_data(gps: GPSCoordinates) -> bool:
    """Check if GPS data contains valid coordinates."""
    # Check essential fields (lat/lng must be present and within valid ranges)
    if gps.lat is None or gps.lng is None:
        logging.warning("Invalid GPS data: Missing latitude or longitude")
        return False

    if not -90 <= gps.lat <= 90 or not -180 <= gps.lng <= 180:
        logging.warning("Invalid GPS data: Latitude/longitude out of valid range")
        return False

    # Check if we have a valid timestamp
    if not gps.loc_ts:
        logging.warning("Invalid GPS data: Missing location timestamp")
        return False

    return True


def store_gps_coordinates(gps: GPSCoordinates) -> None:
    """Store GPS coordinates in the database with UTC timestamp."""
    if not _is_valid_gps_data(gps):
        logging.warning("Skipping storage of invalid GPS data: %s", gps)
        return

    now_utc = datetime.now(timezone.utc)

    with SessionLocal() as session:
        try:
            gps_entry = GPSData(
                latitude=gps.lat,
                longitude=gps.lng,
                altitude=gps.alt,
                speed=gps.spd,
                heading=gps.heading,
                pdop=gps.pdop,
                hdop=gps.hdop,
                vdop=gps.vdop,
                timestamp=now_utc,
                location_timestamp=gps.loc_ts,
            )
            session.add(gps_entry)
            session.commit()
        except Exception as e:
            logging.error("Error storing GPS coordinates: %s", e)
            session.rollback()
            raise


def purge_old_messages(days: int = 14) -> None:
    """Purge messages older than specified days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logging.info(
        "Purging messages older than %d days (cutoff: %s UTC).",
        days,
        cutoff.strftime(UTC_TIME_FORMAT),
    )

    with SessionLocal() as session:
        try:
            deleted = session.query(Message).filter(Message.timestamp < cutoff).delete()
            session.commit()
            logging.info("Purged %d old messages successfully.", deleted)
        except SQLAlchemyError as e:
            logging.error("Error purging old messages: %s", e)
            session.rollback()


def purge_old_gps_data(days: int = 14) -> None:
    """Purge GPS data older than specified days, but only if it has been sent to MQTT."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logging.info(
        "Purging GPS data older than %d days (cutoff: %s UTC).",
        days,
        cutoff.strftime(UTC_TIME_FORMAT),
    )

    with SessionLocal() as session:
        try:
            # Get the oldest outbound message time to ensure we don't delete unsent data
            last_outbound = (
                session.query(OutboundGPSData)
                .order_by(OutboundGPSData.last_sent.desc())
                .first()
            )
            if not last_outbound:
                logging.info("No outbound GPS data found, skipping purge.")
                return

            # Delete GPS data that is both older than cutoff and older than the last sent message
            deleted = (
                session.query(GPSData)
                .filter(
                    GPSData.timestamp < cutoff,
                    GPSData.timestamp <= last_outbound.last_sent,
                )
                .delete()
            )

            # Clean up old outbound records
            deleted_outbound = (
                session.query(OutboundGPSData)
                .filter(OutboundGPSData.last_sent < cutoff)
                .delete()
            )

            session.commit()
            logging.info(
                "Purged %d old GPS records and %d old outbound records successfully.",
                deleted,
                deleted_outbound,
            )
        except SQLAlchemyError as e:
            logging.error("Error purging old GPS data: %s", e)
            session.rollback()


def purge_old_device_data(days: int = 14) -> None:
    """Purge device data older than specified days, but only if it has been sent to MQTT."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logging.info(
        "Purging device data older than %d days (cutoff: %s UTC).",
        days,
        cutoff.strftime(UTC_TIME_FORMAT),
    )

    with SessionLocal() as session:
        try:
            # Get the oldest outbound message time to ensure we don't delete unsent data
            last_outbound = (
                session.query(OutboundDeviceData)
                .order_by(OutboundDeviceData.last_sent.desc())
                .first()
            )
            if not last_outbound:
                logging.info("No outbound device data found, skipping purge.")
                return

            # Delete device data that is both older than cutoff and older than the last sent message
            deleted = (
                session.query(DeviceData)
                .filter(
                    DeviceData.timestamp < cutoff,
                    DeviceData.timestamp <= last_outbound.last_sent,
                )
                .delete()
            )

            # Clean up old outbound records
            deleted_outbound = (
                session.query(OutboundDeviceData)
                .filter(OutboundDeviceData.last_sent < cutoff)
                .delete()
            )

            session.commit()
            logging.info(
                "Purged %d old device records and %d old outbound records successfully.",
                deleted,
                deleted_outbound,
            )
        except SQLAlchemyError as e:
            logging.error("Error purging old device data: %s", e)
            session.rollback()

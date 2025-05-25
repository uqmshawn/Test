"""Database models for the application using SQLAlchemy ORM."""

from __future__ import annotations
import os
from datetime import datetime
from typing import Final, Optional, Dict, Any

from sqlalchemy import (
    create_engine,
    String,
    Integer,
    Float,
    LargeBinary,
    Text,
    TIMESTAMP,
    Index,
    BigInteger,
    DateTime,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column

# Determine if running in Docker or locally
is_docker = os.environ.get("DOCKER_CONTAINER", "").lower() == "true"
DEFAULT_DB_URL = (
    "postgresql://hurtec:hurtec@postgres/hurtec"
    if is_docker
    else "postgresql://hurtec:hurtec@localhost/hurtec"
)
DATABASE_URL: Final = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


class Message(Base):
    """Model for storing MQTT messages."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    sent_on: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_messages_timestamp_topic", "timestamp", "topic"),)


class ServiceStatus(Base):
    """Model for storing service status information."""

    __tablename__ = "service_status"

    service_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    status_message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )


class GPSData(Base):
    """Model for storing GPS location data from devices."""

    __tablename__ = "gps_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float(precision=9), nullable=False)
    longitude: Mapped[float] = mapped_column(Float(precision=9), nullable=False)
    altitude: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    speed: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    heading: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    pdop: Mapped[float] = mapped_column(Float(precision=4), nullable=False)
    hdop: Mapped[float] = mapped_column(Float(precision=4), nullable=False)
    vdop: Mapped[float] = mapped_column(Float(precision=4), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    location_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_gps_location", "latitude", "longitude"),
        Index("idx_gps_timestamp", "timestamp", "location_timestamp"),
    )


class Certificate(Base):
    """Model for storing certificate files and related metadata."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, index=True
    )
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)


class Settings(Base):
    """Model for storing application-wide settings."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iot_environment: Mapped[str] = mapped_column(
        String(50), nullable=False, default="test"
    )
    tenant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_name: Mapped[str] = mapped_column(String(100), nullable=False)
    aws_iot_endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )


class OutboundGPSData(Base):
    """Model for storing GPS data messages to be sent to external systems."""

    __tablename__ = "outbound_gps_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_sent: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DeviceData(Base):
    """Model for storing raw device data received from devices."""

    __tablename__ = "device_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    measures: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("idx_device_data_timestamp", "timestamp"),)


class OutboundDeviceData(Base):
    """Model for storing device data messages to be sent to external systems."""

    __tablename__ = "outbound_device_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_sent: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)


class VehicleData(Base):
    """Model for storing vehicle data from Peplink API."""

    __tablename__ = "vehicle_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ign_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ign_state: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    io_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    io_state: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    __table_args__ = (Index("idx_vehicle_data_timestamp", "timestamp"),)


class OutboundVehicleData(Base):
    """Model for storing vehicle data messages to be sent to external systems."""

    __tablename__ = "outbound_vehicle_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_sent: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)


class BMSData(Base):
    """Model for storing Battery Management System (BMS) data."""

    __tablename__ = "bms_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    volts: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    amps: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    watts: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    remaining_ah: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    full_ah: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    charging: Mapped[bool] = mapped_column(Boolean, nullable=False)
    temperature: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    state_of_charge: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    state_of_health: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    integer_soc: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("idx_bms_data_timestamp", "timestamp"),)


class MultiPlusData(Base):
    """Model for storing MultiPlus inverter/charger data."""

    __tablename__ = "multiplus_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    volts_in: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    amps_in: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    watts_in: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    freq_in: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    volts_out: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    amps_out: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    watts_out: Mapped[float] = mapped_column(Float(precision=6), nullable=False)
    freq_out: Mapped[float] = mapped_column(Float(precision=6), nullable=False)

    __table_args__ = (Index("idx_multiplus_data_timestamp", "timestamp"),)

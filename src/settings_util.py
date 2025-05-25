"""Utility functions for managing application settings."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from models import Settings, SessionLocal


def load_settings() -> Dict[str, Any]:
    """Load settings from the database.

    Returns:
        Dict[str, Any]: Dictionary containing the settings
    """
    try:
        with SessionLocal() as session:
            settings = session.query(Settings).first()
            if settings:
                return {
                    "iot_environment": settings.iot_environment,
                    "tenant_name": settings.tenant_name,
                    "device_name": settings.device_name,
                    "aws_iot_endpoint": settings.aws_iot_endpoint,
                }
    except Exception as e:
        logging.error("Error loading settings: %s", e)
    return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to the database.

    Args:
        settings: Dictionary containing the settings to save
    """
    try:
        with SessionLocal() as session:
            db_settings = session.query(Settings).first()
            if db_settings:
                # Update existing settings
                db_settings.iot_environment = settings.get("iot_environment", "test")
                db_settings.tenant_name = settings.get("tenant_name", "")
                db_settings.device_name = settings.get("device_name", "")
                db_settings.aws_iot_endpoint = settings.get("aws_iot_endpoint", "")
                db_settings.updated_at = datetime.now(timezone.utc)
            else:
                # Create new settings
                new_settings = Settings(
                    iot_environment=settings.get("iot_environment", "test"),
                    tenant_name=settings.get("tenant_name", ""),
                    device_name=settings.get("device_name", ""),
                    aws_iot_endpoint=settings.get("aws_iot_endpoint", ""),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(new_settings)
            session.commit()
    except Exception as e:
        logging.error("Error saving settings: %s", e)
        raise

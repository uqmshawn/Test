"""Utility module for managing application configuration and environment settings.

This module provides functions to determine the current environment mode,
including a special "mock" mode for local development that simulates
external services without making real connections.
"""

import os
import sys
import logging
from typing import Literal, Optional, Union, Dict, Any

# Environment types - these are the actual deployment environments
# Mock mode is orthogonal to these environments and controlled separately
EnvType = Literal["test", "prod", "dev"]


def is_mock_mode() -> bool:
    """Check if the application is running in mock mode.

    Mock mode is enabled by setting the MOCK_MODE environment variable to 'true'.
    This is intended for local development and testing without connecting to real services.

    Tests will always run in normal mode regardless of the MOCK_MODE environment variable.

    Returns:
        bool: True if mock mode is enabled, False otherwise
    """
    # Check if we're running in a test environment
    # This ensures tests always run in normal mode
    if "pytest" in sys.modules:
        return False

    mock_mode = os.environ.get("MOCK_MODE", "").lower() == "true"
    if mock_mode:
        logging.info("Running in MOCK MODE - external services will be simulated")
    return mock_mode


def get_mqtt_broker_address() -> str:
    """Get the MQTT broker address based on the current environment.

    Returns:
        str: The MQTT broker address
    """
    # Use the environment variable or default, regardless of mock mode
    # This ensures we always use the same MQTT broker configuration
    return os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto")

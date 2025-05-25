"""Tests for mock_gps.py module."""

import pytest
from unittest.mock import patch, MagicMock, ANY
import threading

from src.mock_gps import start_mock_gps_generator


def test_start_mock_gps_generator():
    """Test that the mock GPS generator thread is started correctly."""
    with patch("src.mock_gps.threading.Thread") as mock_thread:
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        # Call the function
        result = start_mock_gps_generator()

        # Verify the thread was created with the correct parameters
        mock_thread.assert_called_once_with(
            target=ANY,  # We don't need to check the exact function
            daemon=True,
            name="mock_gps_thread",
        )

        # Verify the thread was started
        mock_thread_instance.start.assert_called_once()

        # Verify the function returns the thread
        assert result == mock_thread_instance

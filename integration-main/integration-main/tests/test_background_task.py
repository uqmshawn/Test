"""Tests for background_task.py GPS-related functions."""

import pytest
from unittest.mock import MagicMock, patch
import requests
from typing import Optional

from background_task import (
    _get_gps_response,
    _process_gps_data,
    fetch_router_gps,
)
from data_access import GPSCoordinates


def test_get_gps_response_success(mock_requests_session: MagicMock) -> None:
    """Test successful GPS response retrieval."""
    # Arrange
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_requests_session.get.return_value = mock_response
    endpoint = "https://192.168.1.1/api/info.location"

    # Act
    response, needs_auth = _get_gps_response(mock_requests_session, endpoint)

    # Assert
    assert response == mock_response
    assert not needs_auth
    mock_requests_session.get.assert_called_once_with(endpoint, verify=False)


def test_get_gps_response_unauthorized(mock_requests_session: MagicMock) -> None:
    """Test GPS response when unauthorized."""
    # Arrange
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 401
    mock_requests_session.get.return_value = mock_response
    endpoint = "https://192.168.1.1/api/info.location"

    # Act
    response, needs_auth = _get_gps_response(mock_requests_session, endpoint)

    # Assert
    assert response == mock_response
    assert needs_auth


def test_process_gps_data_success(sample_gps_data: dict) -> None:
    """Test successful GPS data processing."""
    # Act
    result = _process_gps_data(sample_gps_data)

    # Assert
    assert result is not None
    # Check each field individually
    assert result.lat == 10.0
    assert result.lng == 20.0
    assert result.alt == 30.0
    assert result.spd == 5.0
    assert result.heading == 90.0
    assert result.pdop == 1.0
    assert result.hdop == 0.8
    assert result.vdop == 0.6
    assert result.loc_ts == 1678886400


def test_process_gps_data_invalid_status() -> None:
    """Test GPS data processing with invalid status."""
    # Arrange
    invalid_data = {"stat": "error", "code": 500, "message": "Internal Server Error"}

    # Act
    result = _process_gps_data(invalid_data)

    # Assert
    assert result is None


def test_process_gps_data_unauthorized() -> None:
    """Test GPS data processing with unauthorized status."""
    # Arrange
    unauthorized_data = {"stat": "error", "code": 401, "message": "Unauthorized"}

    # Act
    result = _process_gps_data(unauthorized_data)

    # Assert
    assert result is None


def test_process_gps_data_missing_fields() -> None:
    """Test GPS data processing with missing required fields."""
    # Arrange
    incomplete_data = {
        "stat": "ok",
        "response": {
            "location": {
                "latitude": 10.0,
                # missing longitude and timestamp
            }
        },
    }

    # Act
    result = _process_gps_data(incomplete_data)

    # Assert
    assert result is None


@patch("router_utils.re_authenticate")
def test_fetch_router_gps_success(
    mock_re_authenticate: MagicMock,
    mock_requests_session: MagicMock,
    sample_gps_data: dict,
) -> None:
    """Test successful GPS data fetching."""
    # Arrange
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = sample_gps_data
    mock_requests_session.get.return_value = mock_response

    router_ip = "192.168.1.1"
    credentials = {"router_userid": "admin", "router_password": "pw"}

    # Act
    session, gps_result = fetch_router_gps(
        mock_requests_session, router_ip, credentials
    )

    # Assert
    assert session == mock_requests_session
    assert gps_result is not None
    assert isinstance(gps_result, GPSCoordinates)
    assert gps_result.lat == 10.0
    assert gps_result.lng == 20.0


@patch("background_task.re_authenticate", autospec=True)
def test_fetch_router_gps_unauthorized_retry(
    mock_re_authenticate: MagicMock,
    mock_requests_session: MagicMock,
    sample_gps_data: dict,
) -> None:
    """Test GPS fetching with unauthorized response and successful retry."""
    # Arrange
    # First response is 401
    mock_unauthorized_response = MagicMock(spec=requests.Response)
    mock_unauthorized_response.status_code = 401
    mock_unauthorized_response.json.return_value = {
        "stat": "error",
        "code": 401,
        "message": "Unauthorized",
    }

    # Second response after re-auth is successful
    mock_success_response = MagicMock(spec=requests.Response)
    mock_success_response.status_code = 200
    mock_success_response.json.return_value = sample_gps_data

    # New session after re-auth
    mock_new_session = MagicMock(spec=requests.Session)
    mock_new_session.get.return_value = mock_success_response

    # Set up the mock responses
    mock_requests_session.get.return_value = mock_unauthorized_response
    mock_re_authenticate.return_value = mock_new_session

    router_ip = "192.168.1.1"
    credentials = {"router_userid": "admin", "router_password": "pw"}

    # Act
    session, gps_result = fetch_router_gps(
        mock_requests_session, router_ip, credentials
    )

    # Assert
    mock_re_authenticate.assert_called_once_with(router_ip, credentials)
    assert gps_result is not None
    assert isinstance(gps_result, GPSCoordinates)
    assert gps_result.lat == 10.0
    assert gps_result.lng == 20.0

    # Verify the session was updated
    assert mock_requests_session.get.call_count == 1  # Initial unauthorized request
    assert mock_new_session.get.call_count == 1  # Successful request with new session

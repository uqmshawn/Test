"""Tests for the CertificateManager class in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import tempfile
import os
import ssl
import paho.mqtt.client as mqtt
import sys

# Create mocks for all required modules
mock_logger_setup = MagicMock()
mock_logger_setup.set_process_name = MagicMock(return_value=None)
sys.modules["logger_setup"] = mock_logger_setup

# Mock the models module
mock_models = MagicMock()


# Create a proper Certificate mock class
class MockCertificate:
    """Mock Certificate class for testing."""

    def __init__(self, filename, content):
        self.filename = filename
        self.content = content


# Create a proper SQLAlchemy model mock
class MockCertificateModel:
    """Mock SQLAlchemy model for Certificate."""

    filename = MagicMock()

    @classmethod
    def in_(cls, values):
        return MagicMock()


mock_models.Certificate = MockCertificateModel


# Create mock session factory
class MockSession:
    def __init__(self):
        self.add = MagicMock()
        self.commit = MagicMock()
        self.query = MagicMock()
        self.rollback = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


mock_models.SessionLocal = MockSession
sys.modules["models"] = mock_models

# Mock other imports
sys.modules["mqtt_utils"] = MagicMock()
sys.modules["settings_util"] = MagicMock()
sys.modules["device_util"] = MagicMock()

from src.mqtt_broker import CertificateManager


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = MockSession()
    return session


@pytest.fixture
def cert_manager():
    """Create a CertificateManager instance."""
    return CertificateManager()


def test_cert_manager_init(cert_manager):
    """Test CertificateManager initialization."""
    assert cert_manager.required_certs == ["ca.pem", "cert.crt", "private.key"]
    assert cert_manager._cert_data == {}


def test_get_missing_certs_all_missing(cert_manager, mock_session):
    """Test _get_missing_certs when all certificates are missing."""
    # Mock the database query to return no certificates
    mock_session.query.return_value.filter.return_value.all.return_value = []

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        missing = cert_manager._get_missing_certs()

    assert missing == ["ca.pem", "cert.crt", "private.key"]


def test_get_missing_certs_some_missing(cert_manager, mock_session):
    """Test _get_missing_certs when some certificates are missing."""
    # Mock the database query to return some certificates
    mock_certs = [
        MockCertificate("ca.pem", b"ca_content"),
        MockCertificate("cert.crt", b"cert_content"),
    ]
    mock_session.query.return_value.filter.return_value.all.return_value = mock_certs

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        missing = cert_manager._get_missing_certs()

    assert missing == ["private.key"]


def test_get_missing_certs_none_missing(cert_manager, mock_session):
    """Test _get_missing_certs when no certificates are missing."""
    # Mock the database query to return all certificates
    mock_certs = [
        MockCertificate("ca.pem", b"ca_content"),
        MockCertificate("cert.crt", b"cert_content"),
        MockCertificate("private.key", b"key_content"),
    ]
    mock_session.query.return_value.filter.return_value.all.return_value = mock_certs

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        missing = cert_manager._get_missing_certs()

    assert missing == []


def test_load_cert_data(cert_manager, mock_session):
    """Test _load_cert_data."""
    # Mock the database query to return certificates
    mock_certs = [
        MockCertificate("ca.pem", b"ca_content"),
        MockCertificate("cert.crt", b"cert_content"),
        MockCertificate("private.key", b"key_content"),
    ]
    mock_session.query.return_value.filter.return_value.all.return_value = mock_certs

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        cert_manager._load_cert_data()

    assert cert_manager._cert_data == {
        "ca.pem": b"ca_content",
        "cert.crt": b"cert_content",
        "private.key": b"key_content",
    }


def test_write_temp_cert(cert_manager):
    """Test _write_temp_cert."""
    # Set up certificate data
    cert_manager._cert_data = {"ca.pem": b"ca_content"}

    # Mock tempfile.mkdtemp to return a known directory
    with patch("tempfile.mkdtemp", return_value=os.path.join("tmp", "test_dir")):
        # Mock open to avoid actual file operations
        with patch("builtins.open", mock_open()) as mock_file:
            temp_path = cert_manager._write_temp_cert("ca.pem")

            # Check that the file was opened with the correct path
            expected_path = os.path.join("tmp", "test_dir", "ca.pem")
            mock_file.assert_called_once_with(expected_path, "wb")

            # Check that the content was written
            mock_file.return_value.__enter__().write.assert_called_once_with(
                b"ca_content"
            )

            # Check that the correct path was returned
            assert temp_path == expected_path


def test_configure_client(cert_manager):
    """Test configure_client."""
    # Set up certificate data
    cert_manager._cert_data = {
        "ca.pem": b"ca_content",
        "cert.crt": b"cert_content",
        "private.key": b"key_content",
    }

    # Create a mock MQTT client
    mock_client = MagicMock(spec=mqtt.Client)

    # Mock _write_temp_cert to return known paths
    with patch.object(
        cert_manager,
        "_write_temp_cert",
        side_effect=[
            os.path.join("tmp", "test_dir", "ca.pem"),
            os.path.join("tmp", "test_dir", "cert.crt"),
            os.path.join("tmp", "test_dir", "private.key"),
        ],
    ):
        cert_manager.configure_client(mock_client)

    # Check that tls_set was called with the correct parameters
    mock_client.tls_set.assert_called_once_with(
        ca_certs=os.path.join("tmp", "test_dir", "ca.pem"),
        certfile=os.path.join("tmp", "test_dir", "cert.crt"),
        keyfile=os.path.join("tmp", "test_dir", "private.key"),
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLSv1_2,
        ciphers=None,
    )


def test_wait_for_certs_all_present(cert_manager):
    """Test wait_for_certs when all certificates are present."""
    # Mock _get_missing_certs to return an empty list (all certs present)
    with patch.object(cert_manager, "_get_missing_certs", return_value=[]):
        with patch.object(cert_manager, "_load_cert_data") as mock_load:
            cert_manager.wait_for_certs()

            # _load_cert_data should be called once
            mock_load.assert_called_once()


def test_wait_for_certs_some_missing(cert_manager):
    """Test wait_for_certs when some certificates are missing."""
    # Mock _get_missing_certs to first return some missing certs, then no missing certs
    mock_get_missing = MagicMock(side_effect=[["ca.pem"], []])

    with patch.object(
        cert_manager, "_get_missing_certs", new=mock_get_missing
    ), patch.object(cert_manager, "_load_cert_data") as mock_load, patch(
        "time.sleep"
    ) as mock_sleep:  # Mock sleep to speed up test

        cert_manager.wait_for_certs()

        # Verify the mocks were called correctly
        assert mock_get_missing.call_count == 2
        mock_load.assert_called_once()
        mock_sleep.assert_called_once_with(10)

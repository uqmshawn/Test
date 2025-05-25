"""Flask web application providing a web interface for the Hurtec integration system.

This provides functionality for viewing message status, system configuration, and logs.
"""

import os
import json
import re
import logging
import time
import threading
from datetime import datetime, timezone
from functools import wraps
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Callable,
    TypeVar,
    cast,
    Any,
    Tuple,
    TypedDict,
)

import paho.mqtt.client as mqtt
import requests
import urllib3
import bcrypt
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
    Response,
)
from flask.typing import ResponseReturnValue
from flask_socketio import SocketIO
from sqlalchemy import desc
from urllib3.exceptions import InsecureRequestWarning

from settings_util import load_settings, save_settings
import logger_setup
from models import Message, Certificate, SessionLocal, BMSData, MultiPlusData
from secrets_util import load_secrets
from router_utils import router_login
import config_util


logger_setup.set_process_name("web_app")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
socketio = SocketIO(
    app, async_mode="threading"
)  # Initialize SocketIO with threading support

F = TypeVar("F", bound=Callable[..., ResponseReturnValue])

# Dictionary to store session-specific MQTT clients and their subscribed topics
mqtt_clients = {}
# Dictionary to store received messages for each session
mqtt_messages = {}
# Lock for thread-safe access to shared resources
mqtt_lock = threading.Lock()


class CerboMqttClient:
    """Manages MQTT client for Cerbo GX subscriptions."""

    def __init__(self, session_id: str, broker_config: Dict[str, Any]):
        """Initialize a new MQTT client for the given session.

        Args:
            session_id: Flask session ID
            broker_config: Cerbo MQTT broker configuration
        """
        self.session_id = session_id
        self.broker_ip = broker_config.get("broker_ip", "")
        self.broker_port = int(broker_config.get("broker_port", 1883))
        self.username = broker_config.get("username", "")
        self.password = broker_config.get("password", "")
        self.subscribed_topics = set()
        self.client = None
        self.connected = False
        self.client_thread = None

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback for when the client receives a CONNACK response from the server."""
        if rc == 0:
            logging.info(f"MQTT client connected for session {self.session_id}")
            self.connected = True

            # Resubscribe to all topics
            for topic in self.subscribed_topics:
                self.client.subscribe(topic)
        else:
            logging.error(
                f"MQTT connection failed for session {self.session_id} with code {rc}"
            )
            self.connected = False

    def on_disconnect(self, client, userdata, rc, properties=None):
        """Callback for when the client disconnects."""
        logging.info(
            f"MQTT client disconnected for session {self.session_id} with code {rc}"
        )
        self.connected = False

    def on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the server."""
        try:
            payload = msg.payload.decode("utf-8")
            # Try to parse JSON if possible
            try:
                payload_json = json.loads(payload)
                payload = payload_json
            except json.JSONDecodeError:
                pass  # Not JSON, keep as string

            with mqtt_lock:
                if self.session_id not in mqtt_messages:
                    mqtt_messages[self.session_id] = []

                # Store the received message with a timestamp
                mqtt_messages[self.session_id].append(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "topic": msg.topic,
                        "payload": payload,
                    }
                )

                # Limit the number of stored messages to prevent memory issues
                if len(mqtt_messages[self.session_id]) > 100:
                    mqtt_messages[self.session_id] = mqtt_messages[self.session_id][
                        -100:
                    ]

            logging.info(
                f"MQTT message received on {msg.topic} for session {self.session_id}"
            )
        except Exception as e:
            logging.error(f"Error processing MQTT message: {str(e)}")

    def connect(self):
        """Connect the MQTT client to the broker."""
        if self.client is None:
            # Create a unique client ID based on session ID and timestamp
            client_id = f"hurtec-cerbo-{self.session_id}-{int(time.time())}"
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5)

            # Set callbacks
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect

            # Set authentication if provided
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)

        if not self.connected:
            try:
                self.client.connect(self.broker_ip, self.broker_port)
                self.client.loop_start()  # Start the background thread
                return True
            except Exception as e:
                logging.error(f"Failed to connect MQTT client: {str(e)}")
                return False
        return True

    def disconnect(self):
        """Disconnect the MQTT client."""
        if self.client and self.connected:
            try:
                self.client.loop_stop()
                self.client.disconnect()
                self.connected = False
                logging.info(f"MQTT client disconnected for session {self.session_id}")
            except Exception as e:
                logging.error(f"Error disconnecting MQTT client: {str(e)}")

    def subscribe(self, topic: str) -> bool:
        """Subscribe to an MQTT topic.

        Args:
            topic: The topic to subscribe to

        Returns:
            True if subscription was successful, False otherwise
        """
        if not self.connected and not self.connect():
            return False

        try:
            result, mid = self.client.subscribe(topic)
            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscribed_topics.add(topic)
                logging.info(f"Subscribed to {topic} for session {self.session_id}")
                return True
            else:
                logging.error(
                    f"Failed to subscribe to {topic}: {mqtt.error_string(result)}"
                )
                return False
        except Exception as e:
            logging.error(f"Error subscribing to topic {topic}: {str(e)}")
            return False

    def unsubscribe(self, topic: str) -> bool:
        """Unsubscribe from an MQTT topic.

        Args:
            topic: The topic to unsubscribe from

        Returns:
            True if unsubscription was successful, False otherwise
        """
        if not self.connected:
            return False

        try:
            result, mid = self.client.unsubscribe(topic)
            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscribed_topics.discard(topic)
                logging.info(f"Unsubscribed from {topic} for session {self.session_id}")
                return True
            else:
                logging.error(
                    f"Failed to unsubscribe from {topic}: {mqtt.error_string(result)}"
                )
                return False
        except Exception as e:
            logging.error(f"Error unsubscribing from topic {topic}: {str(e)}")
            return False

    def get_subscribed_topics(self) -> List[str]:
        """Get the list of subscribed topics.

        Returns:
            List of subscribed topics
        """
        return list(self.subscribed_topics)


def get_mqtt_client(session_id: str, broker_config: Dict[str, Any]) -> CerboMqttClient:
    """Get or create an MQTT client for the given session.

    Args:
        session_id: Flask session ID
        broker_config: Cerbo MQTT broker configuration

    Returns:
        MQTT client for the session
    """
    with mqtt_lock:
        if session_id not in mqtt_clients:
            mqtt_clients[session_id] = CerboMqttClient(session_id, broker_config)
        return mqtt_clients[session_id]


def cleanup_mqtt_client(session_id: str):
    """Clean up MQTT client resources for the given session.

    Args:
        session_id: Flask session ID
    """
    with mqtt_lock:
        if session_id in mqtt_clients:
            mqtt_clients[session_id].disconnect()
            del mqtt_clients[session_id]

        if session_id in mqtt_messages:
            del mqtt_messages[session_id]


@app.context_processor
def inject_template_vars() -> Dict[str, Any]:
    """Inject variables into all templates.

    This injects:
    - current UTC time
    - mock mode status

    Returns:
        Dict with template variables
    """
    return {
        "now": datetime.now(timezone.utc),
        "is_mock_mode": config_util.is_mock_mode(),
    }


def format_message_dict(
    msg: Message, include_error: bool = False, include_sent: bool = False
) -> Dict[str, Union[int, str]]:
    """Format a Message object into a dictionary for display.

    Args:
        msg: The Message object to format
        include_error: Whether to include the error field
        include_sent: Whether to include the sent_on field

    Returns:
        Dict containing formatted message data
    """
    data = {
        "id": msg.id,
        "timestamp": msg.timestamp,
        "topic": msg.topic,
        "payload": msg.payload,
    }

    if include_error:
        data["error"] = msg.last_error or ""
    if include_sent:
        data["sent_on"] = msg.sent_on or ""

    return data


def load_users() -> Dict[str, str]:
    """Load user credentials from the secrets file."""
    try:
        secrets = load_secrets()
        passwords: Union[str, Dict[str, str]] = secrets.get("passwords", {})
        if isinstance(passwords, str):
            passwords = {}
        if not isinstance(passwords, dict):
            logging.error(
                "Invalid type for passwords: expected dict, got %s", type(passwords)
            )
            return {}
        logging.info("Successfully loaded %d users from secrets file", len(passwords))
        for user in passwords.keys():
            logging.info("Found user: %s", user)
        return {str(k): str(v) for k, v in passwords.items()}
    except Exception as e:
        logging.error("Error loading users: %s", str(e))
    return {}


def login_required(f: F) -> F:
    """Decorator to require login for routes.

    Args:
        f: The function to decorate

    Returns:
        The decorated function
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> ResponseReturnValue:
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return cast(F, decorated_function)


@app.route("/login", methods=["GET", "POST"])  # type: ignore
def login() -> ResponseReturnValue:
    """Handle login requests.

    Returns:
        ResponseReturnValue: Either the login page or a redirect response
    """
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        users = load_users()

        logging.info("Login attempt for user: %s", username)
        logging.info("Number of configured users: %d", len(users))

        hashed_password = users.get(username)
        if not hashed_password:
            logging.warning(
                "Login failed: User '%s' not found in configuration", username
            )
            flash("Invalid username or password")
            return cast(ResponseReturnValue, render_template("login.html"))

        if bcrypt.checkpw(password.encode(), hashed_password.encode()):
            logging.info("Login successful for user: %s", username)
            session["authenticated"] = True
            return redirect(url_for("index"))

        logging.warning("Login failed: Invalid password for user '%s'", username)
        flash("Invalid username or password")
    return cast(ResponseReturnValue, render_template("login.html"))


@app.route("/logout")  # type: ignore
@login_required
def logout() -> ResponseReturnValue:
    """Handle logout requests.

    Returns:
        ResponseReturnValue: Redirect to login page
    """
    # Clean up any MQTT subscription clients for this session
    session_id = str(session.get("_id", ""))
    if session_id:
        cleanup_mqtt_client(session_id)

    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("login"))


@app.route("/")  # type: ignore
@login_required
def index() -> ResponseReturnValue:
    """Render the index page.

    Returns:
        ResponseReturnValue: The rendered template
    """
    return cast(ResponseReturnValue, render_template("index.html"))


@app.route("/status")  # type: ignore
@login_required
def status() -> ResponseReturnValue:
    """Display message status information.

    Returns:
        ResponseReturnValue: The rendered template with message status
    """
    show_queued = request.args.get("show_queued") == "1"
    show_sent = request.args.get("show_sent") == "1"

    queued_data: List[Dict[str, Union[int, str]]] = []
    sent_data: List[Dict[str, Union[int, str]]] = []

    if show_queued:
        with SessionLocal() as db_session:
            queued = db_session.query(Message).filter(Message.sent_on.is_(None)).all()
            queued_data = [
                format_message_dict(msg, include_error=True) for msg in queued
            ]

    if show_sent:
        with SessionLocal() as db_session:
            sent = (
                db_session.query(Message)
                .filter(Message.sent_on.isnot(None))
                .order_by(desc(Message.sent_on))
                .limit(10)
                .all()
            )
            sent_data = [format_message_dict(msg, include_sent=True) for msg in sent]

    return cast(
        ResponseReturnValue,
        render_template(
            "status.html",
            queued_data=queued_data,
            sent_data=sent_data,
            show_queued=show_queued,
            show_sent=show_sent,
        ),
    )


@app.route("/config", methods=["GET", "POST"])  # type: ignore
@login_required
def config() -> ResponseReturnValue:
    """Handle configuration management."""
    if request.method == "POST":
        if "cert_file" in request.files:
            file = request.files["cert_file"]
            if file and file.filename:
                try:
                    content = file.read()
                    with SessionLocal() as db_session:
                        # Check if certificate already exists
                        existing_cert = (
                            db_session.query(Certificate)
                            .filter_by(filename=file.filename)
                            .first()
                        )
                        if existing_cert:
                            existing_cert.content = content
                            existing_cert.uploaded_at = datetime.now(timezone.utc)
                        else:
                            new_cert = Certificate(
                                filename=file.filename,
                                content=content,
                                uploaded_at=datetime.now(timezone.utc),
                            )
                            db_session.add(new_cert)
                        db_session.commit()
                    flash(f"Uploaded {file.filename} successfully")
                except Exception as e:
                    flash(f"Error uploading file: {str(e)}", "error")
        else:
            # Get environment selection
            env_selection = request.form.get("iot_environment", "test")

            # If dev environment is selected, use the custom environment name
            if env_selection == "dev":
                custom_env = request.form.get("custom_environment", "").strip()
                if custom_env:
                    env_selection = custom_env
                else:
                    flash(
                        "Custom environment name is required when Development is selected",
                        "error",
                    )
                    env_selection = "dev"  # Keep dev as fallback

            config_data = {
                "iot_environment": env_selection,
                "tenant_name": request.form.get("tenant_name", ""),
                "device_name": request.form.get("device_name", ""),
                "aws_iot_endpoint": request.form.get("aws_iot_endpoint", ""),
            }
            try:
                save_settings(config_data)
                flash("Configuration saved successfully")
            except Exception as e:
                flash(f"Error saving configuration: {str(e)}", "error")

    config_data = load_settings()
    cert_files = ["ca.pem", "cert.crt", "private.key"]
    with SessionLocal() as db_session:
        cert_status = {
            cert: db_session.query(Certificate).filter_by(filename=cert).first()
            is not None
            for cert in cert_files
        }

    return cast(
        ResponseReturnValue,
        render_template("config.html", config=config_data, cert_status=cert_status),
    )


@app.route("/logs")  # type: ignore
@login_required
def logs() -> ResponseReturnValue:
    """Show application logs."""
    selected = request.args.get("log_file", "All logs combined")
    app_logs = []

    def clean_log_line(line: str) -> str:
        """Clean and format a log line."""
        # Remove any leading whitespace/indentation
        return line.lstrip()

    def should_include_log(line: str) -> bool:
        """Determine if a log line should be included."""
        # Filter out _internal.py logs which are just web app asset requests
        if "_internal.py" in line:
            return False
        return True

    if selected == "All logs combined":
        # Read all log files and combine them
        for log_file in ["web_app.log", "mqtt_broker.log", "background_task.log"]:
            try:
                with open(f"/app/logs/{log_file}", "r", encoding="utf-8") as f:
                    app_logs.extend(
                        [
                            {
                                "timestamp": extract_timestamp(line),
                                "content": clean_log_line(line),
                            }
                            for line in f.readlines()
                            if should_include_log(line)
                        ]
                    )
            except FileNotFoundError:
                flash(f"Log file {log_file} not found", "error")
    else:
        # Read selected log file
        try:
            with open(f"/app/logs/{selected}", "r", encoding="utf-8") as f:
                app_logs = [
                    {
                        "timestamp": extract_timestamp(line),
                        "content": clean_log_line(line),
                    }
                    for line in f.readlines()
                    if should_include_log(line)
                ]
        except FileNotFoundError:
            flash(f"Log file {selected} not found", "error")
        except Exception as e:
            flash(f"Error reading log file: {str(e)}", "error")

    # Sort logs by timestamp, most recent first
    app_logs.sort(key=lambda x: x["timestamp"] if x["timestamp"] else "", reverse=True)

    return cast(
        ResponseReturnValue,
        render_template(
            "logs.html",
            log_entries=app_logs,
            log_files=[
                "All logs combined",
                "web_app.log",
                "mqtt_broker.log",
                "background_task.log",
            ],
            selected=selected,
        ),
    )


def _get_log_content(
    log_file: str,
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Get log file content with validation.

    Args:
        log_file: Name of the log file to read

    Returns:
        Tuple of (content, status_code, error_message)
        If successful, content will contain the log data, status_code and error_message will be None
        If error occurs, content will be None, and status_code and error_message will be set
    """
    # Security check - only allow specific log files
    allowed_files = ["web_app.log", "mqtt_broker.log", "background_task.log"]
    if log_file not in allowed_files and log_file != "All logs combined":
        return None, 400, "Invalid log file specified"

    if log_file == "All logs combined":
        # Combine all log files
        combined_content = ""
        for file in allowed_files:
            try:
                with open(f"/app/logs/{file}", "r", encoding="utf-8") as f:
                    combined_content += f"--- {file} ---\n\n"
                    combined_content += f.read()
                    combined_content += "\n\n"
            except FileNotFoundError:
                combined_content += f"--- {file} ---\n\nLog file not found\n\n"
        return combined_content, None, None
    else:
        # Return specific log file
        try:
            with open(f"/app/logs/{log_file}", "r", encoding="utf-8") as f:
                content = f.read()
            return content, None, None
        except FileNotFoundError:
            return None, 404, f"Log file {log_file} not found"
        except Exception as e:
            return None, 500, f"Error reading log file: {str(e)}"


@app.route("/raw_log")  # type: ignore
@login_required
def raw_log() -> ResponseReturnValue:
    """Return the raw log file content."""
    log_file = request.args.get("file", "web_app.log")
    content, status_code, error_message = _get_log_content(log_file)

    if error_message:
        return Response(error_message, status=status_code)

    return Response(content, mimetype="text/plain")


@app.route("/download_log")  # type: ignore
@login_required
def download_log() -> ResponseReturnValue:
    """Download a log file."""
    log_file = request.args.get("file", "web_app.log")
    content, status_code, error_message = _get_log_content(log_file)

    if error_message:
        return Response(error_message, status=status_code)

    response = Response(content, mimetype="text/plain")

    if log_file == "All logs combined":
        response.headers["Content-Disposition"] = "attachment; filename=all_logs.txt"
    else:
        response.headers["Content-Disposition"] = f"attachment; filename={log_file}"

    return response


def extract_timestamp(log_line: str) -> Optional[str]:
    """Extract timestamp from log line if present."""
    timestamp_pattern = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}"
    try:
        match = re.match(timestamp_pattern, log_line)
        if match:
            timestamp_str = match.group(0)
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
            return timestamp.replace(tzinfo=timezone.utc).isoformat()
        return None
    except (ValueError, IndexError):
        return None


@app.route("/mqtt_test", methods=["GET", "POST"])  # type: ignore
@login_required
def mqtt_test() -> ResponseReturnValue:
    """Handle MQTT test message page."""
    message = ""

    # Get current configuration settings
    settings = load_settings()
    iot_env = settings.get("iot_environment", "").strip()
    tenant_name = settings.get("tenant_name", "").strip()
    device_name = settings.get("device_name", "").strip()

    # Create default topic and payload
    default_topic = ""
    default_payload = ""

    # Determine if we're in mock mode
    is_mock_mode = config_util.is_mock_mode()

    if iot_env and tenant_name and device_name:
        # Format a valid status topic for AWS IoT
        default_topic = f"{iot_env}/{tenant_name}/{device_name}/out/status"
        default_payload = json.dumps(
            {
                "message": "Test status message from MQTT test page",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mock_mode": is_mock_mode,
            },
            indent=2,
        )

    if request.method == "POST":
        try:
            topic = request.form.get("topic", "").strip()
            payload = request.form.get("payload", "").strip()

            if topic and payload:
                client = mqtt.Client(protocol=mqtt.MQTTv5)
                client.connect(os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto"), 1883)

                result = client.publish(topic, payload, qos=1)

                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    message = "Message published successfully"
                    flash(message, "success")
                else:
                    message = (
                        f"Failed to publish message: {mqtt.error_string(result.rc)}"
                    )
                    flash(message, "error")

                client.disconnect()
            else:
                flash("Both topic and payload are required", "error")
        except Exception as e:
            flash(f"Error publishing message: {str(e)}", "error")

    return cast(
        ResponseReturnValue,
        render_template(
            "mqtt_test.html",
            message=message,
            default_topic=default_topic,
            default_payload=default_payload,
            iot_env=iot_env,
            tenant_name=tenant_name,
            device_name=device_name,
            is_mock_mode=is_mock_mode,
        ),
    )


class RouterCredentials(TypedDict):
    """Type for router authentication credentials."""

    ip: str
    userid: str
    password: str


def _get_router_auth_info() -> Tuple[RouterCredentials, Optional[str]]:
    """Get router authentication information from secrets.

    Returns:
        Tuple containing router credentials and optional error message.
    """
    error_message = None
    credentials: RouterCredentials = {"ip": "", "userid": "", "password": ""}

    try:
        secrets = load_secrets()
        peplink_api_raw: Any = secrets.get("peplink_api", {})
        peplink_api: Dict[str, Any] = (
            peplink_api_raw if isinstance(peplink_api_raw, dict) else {}
        )
        credentials["ip"] = str(peplink_api.get("router_ip", ""))
        credentials["userid"] = str(peplink_api.get("router_userid", ""))
        credentials["password"] = str(peplink_api.get("router_password", ""))

        if not credentials["ip"]:
            error_message = "Router IP not configured in secrets file"
    except Exception as e:
        error_message = f"Error loading router credentials: {str(e)}"

    return credentials, error_message


def _make_router_api_request(
    session_obj: requests.Session,
    url: str,
    http_verb: str,
    payload_json: Optional[dict] = None,
) -> Tuple[Optional[Union[dict, str]], int, Optional[str]]:
    """Make a request to the router API.

    Args:
        session_obj: Authenticated requests session
        url: Full URL for the API request
        http_verb: HTTP method (GET, POST, PUT, DELETE)
        payload_json: Optional JSON payload for POST/PUT requests

    Returns:
        Tuple of (response_data, status_code, error_message)
    """
    try:
        if http_verb == "GET":
            api_response = session_obj.get(url, verify=False)
        elif http_verb == "POST":
            api_response = session_obj.post(url, json=payload_json, verify=False)
        elif http_verb == "PUT":
            api_response = session_obj.put(url, json=payload_json, verify=False)
        elif http_verb == "DELETE":
            api_response = session_obj.delete(url, verify=False)
        else:
            return None, 0, f"Unsupported HTTP verb: {http_verb}"

        status_code = api_response.status_code

        # Process response
        try:
            response_data = api_response.json()
        except ValueError:
            response_data = api_response.text

        return response_data, status_code, None

    except Exception as e:
        return None, 0, str(e)


def _process_router_api_payload(payload: str) -> Tuple[Optional[dict], Optional[str]]:
    """Process and validate JSON payload.

    Args:
        payload: JSON string to parse

    Returns:
        Tuple of (parsed_json, error_message)
    """
    if not payload:
        return None, None

    try:
        payload_json = json.loads(payload)
        return payload_json, None
    except json.JSONDecodeError:
        return None, "Invalid JSON payload"


def _handle_router_api_request(
    credentials: RouterCredentials,
    endpoint: str,
    http_verb: str,
    payload_json: Optional[dict],
) -> Tuple[Optional[Union[dict, str]], Optional[int], Optional[str]]:
    """Handle the API request including authentication and potential retry.

    Args:
        credentials: Router credentials (ip, userid, password)
        endpoint: API endpoint
        http_verb: HTTP method
        payload_json: JSON payload

    Returns:
        Tuple of (response_data, status_code, error_message)
    """
    # Construct URL
    url = (
        endpoint
        if endpoint.startswith("http")
        else f"https://{credentials['ip']}/{endpoint.lstrip('/')}"
    )

    try:
        # Get authenticated session
        session_obj = router_login(
            credentials["ip"], credentials["userid"], credentials["password"]
        )

        # Make initial request
        response_data, status_code, error = _make_router_api_request(
            session_obj, url, http_verb, payload_json
        )

        # Handle 401 - try to re-authenticate
        if status_code == 401:
            logging.info("API returned 401, attempting to re-authenticate")
            session_obj = router_login(
                credentials["ip"], credentials["userid"], credentials["password"]
            )

            # Retry request with new session
            response_data, status_code, error = _make_router_api_request(
                session_obj, url, http_verb, payload_json
            )

        return response_data, status_code, error

    except Exception as e:
        return None, None, str(e)


@app.route("/router_api_test", methods=["GET", "POST"])  # type: ignore
@login_required
def router_api_test() -> ResponseReturnValue:
    """Handle Router API test page."""
    response_data = None
    error_message = None
    status_code = None

    # Suppress insecure request warnings for router API calls
    urllib3.disable_warnings(InsecureRequestWarning)

    # Get router authentication information
    credentials, auth_error = _get_router_auth_info()
    router_ip = credentials["ip"]  # Keep this to maintain template compatibility

    if auth_error:
        flash(auth_error, "error")

    if request.method == "POST" and router_ip:
        endpoint = request.form.get("endpoint", "").strip()
        http_verb = request.form.get("http_verb", "GET")
        payload = request.form.get("payload", "").strip()

        if not endpoint:
            flash("Endpoint is required", "error")
        else:
            # Process the payload if present
            payload_json, payload_error = _process_router_api_payload(payload)

            if payload_error:
                flash(payload_error, "error")
                return cast(
                    ResponseReturnValue,
                    render_template("router_api_test.html", router_ip=router_ip),
                )

            # Make API request
            response_data, status_code, error_message = _handle_router_api_request(
                credentials,
                endpoint,
                http_verb,
                payload_json,
            )

            if error_message:
                flash(f"Error making API request: {error_message}", "error")

    return cast(
        ResponseReturnValue,
        render_template(
            "router_api_test.html",
            response_data=response_data,
            error_message=error_message,
            status_code=status_code,
            router_ip=router_ip,
        ),
    )


@app.route("/cerbo_test", methods=["GET", "POST"])  # type: ignore
@login_required
def cerbo_test() -> ResponseReturnValue:
    """Handle Cerbo GX MQTT test page.

    This page allows testing communication with a Victron Cerbo GX device via MQTT,
    based on the dbus-flashmq protocol. It allows sending read/write requests and
    subscribing to specific D-Bus paths.

    Returns:
        ResponseReturnValue: The rendered template
    """
    error_message = None
    response_data = None
    cerbo_mqtt_config = {}

    # Initialize session data if not present
    if "cerbo_subscribed_topics" not in session:
        session["cerbo_subscribed_topics"] = []

    subscribed_topics = session["cerbo_subscribed_topics"]

    # Get Cerbo MQTT configuration from secrets
    try:
        secrets = load_secrets()
        cerbo_mqtt_raw = secrets.get("cerbo_mqtt", {})
        cerbo_mqtt_config = cerbo_mqtt_raw if isinstance(cerbo_mqtt_raw, dict) else {}

        if not cerbo_mqtt_config.get("broker_ip"):
            flash("Cerbo MQTT broker IP not configured in secrets.toml file", "warning")
    except Exception as e:
        flash(f"Error loading Cerbo MQTT configuration: {str(e)}", "error")

    # Get the session ID to manage client-specific subscriptions
    session_id = str(session.get("_id", ""))
    if not session_id:
        session_id = str(os.getpid())

    # Get received messages for this session
    with mqtt_lock:
        received_messages = mqtt_messages.get(session_id, [])

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "read":
            # Handle read request
            try:
                topic = request.form.get("read_topic", "").strip()
                payload = request.form.get("read_payload", "").strip()

                if not topic:
                    flash("Topic is required for read operation", "error")
                else:
                    broker_ip = cerbo_mqtt_config.get("broker_ip", "")
                    broker_port = int(cerbo_mqtt_config.get("broker_port", 1883))
                    broker_username = cerbo_mqtt_config.get("username", "")
                    broker_password = cerbo_mqtt_config.get("password", "")

                    # Setup MQTT client
                    client = mqtt.Client(
                        client_id=f"hurtec-web-{os.getpid()}", protocol=mqtt.MQTTv5
                    )

                    # Set auth if provided
                    if broker_username and broker_password:
                        client.username_pw_set(broker_username, broker_password)

                    try:
                        # Connect to broker
                        client.connect(broker_ip, broker_port)

                        # Publish request
                        result = client.publish(topic, payload, qos=1)

                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            flash(
                                f"Read request sent to {topic} successfully", "success"
                            )
                        else:
                            flash(
                                f"Failed to send read request: {mqtt.error_string(result.rc)}",
                                "error",
                            )
                    finally:
                        # Ensure client is disconnected even if an exception occurs
                        client.disconnect()
            except Exception as e:
                flash(f"Error sending Cerbo MQTT read request: {str(e)}", "error")

        elif action == "write":
            # Handle write request
            try:
                topic = request.form.get("write_topic", "").strip()
                payload = request.form.get("write_payload", "").strip()

                if not topic or not payload:
                    flash(
                        "Both topic and payload are required for write operation",
                        "error",
                    )
                else:
                    broker_ip = cerbo_mqtt_config.get("broker_ip", "")
                    broker_port = int(cerbo_mqtt_config.get("broker_port", 1883))
                    broker_username = cerbo_mqtt_config.get("username", "")
                    broker_password = cerbo_mqtt_config.get("password", "")

                    # Setup MQTT client
                    client = mqtt.Client(
                        client_id=f"hurtec-web-{os.getpid()}", protocol=mqtt.MQTTv5
                    )

                    # Set auth if provided
                    if broker_username and broker_password:
                        client.username_pw_set(broker_username, broker_password)

                    try:
                        # Connect to broker
                        client.connect(broker_ip, broker_port)

                        # Publish write request
                        result = client.publish(topic, payload, qos=1)

                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            flash(
                                f"Write request sent to {topic} successfully", "success"
                            )
                        else:
                            flash(
                                f"Failed to send write request: {mqtt.error_string(result.rc)}",
                                "error",
                            )
                    finally:
                        # Ensure client is disconnected even if an exception occurs
                        client.disconnect()
            except Exception as e:
                flash(f"Error sending Cerbo MQTT write request: {str(e)}", "error")

        elif action == "subscribe":
            # Handle subscription request
            topic = request.form.get("subscribe_topic", "").strip()
            if not topic:
                flash("Topic is required for subscription", "error")
            else:
                # Get or create MQTT client for this session
                mqtt_client = get_mqtt_client(session_id, cerbo_mqtt_config)

                # Subscribe to the topic
                if mqtt_client.subscribe(topic):
                    if topic not in subscribed_topics:
                        subscribed_topics.append(topic)
                        session["cerbo_subscribed_topics"] = subscribed_topics
                        session.modified = True
                    flash(f"Successfully subscribed to {topic}", "success")
                else:
                    flash(f"Failed to subscribe to {topic}", "error")

        elif action == "unsubscribe":
            # Handle unsubscribe request
            topic = request.form.get("topic", "").strip()
            if topic:
                # Get MQTT client for this session
                mqtt_client = get_mqtt_client(session_id, cerbo_mqtt_config)

                # Unsubscribe from the topic
                if mqtt_client.unsubscribe(topic):
                    if topic in subscribed_topics:
                        subscribed_topics.remove(topic)
                        session["cerbo_subscribed_topics"] = subscribed_topics
                        session.modified = True
                    flash(f"Successfully unsubscribed from {topic}", "success")
                else:
                    flash(f"Failed to unsubscribe from {topic}", "error")

        elif action == "clear_messages":
            # Clear received messages
            with mqtt_lock:
                if session_id in mqtt_messages:
                    mqtt_messages[session_id] = []
            flash("Cleared message history", "success")

    # Check if there are any subscriptions but no active client
    if subscribed_topics and session_id not in mqtt_clients:
        mqtt_client = get_mqtt_client(session_id, cerbo_mqtt_config)
        for topic in subscribed_topics:
            mqtt_client.subscribe(topic)

    return cast(
        ResponseReturnValue,
        render_template(
            "cerbo_test.html",
            error_message=error_message,
            response_data=response_data,
            broker_ip=cerbo_mqtt_config.get("broker_ip", ""),
            broker_port=cerbo_mqtt_config.get("broker_port", 1883),
            broker_username=cerbo_mqtt_config.get("username", ""),
            has_password=bool(cerbo_mqtt_config.get("password")),
            portal_id=cerbo_mqtt_config.get("portal_id", "victron"),
            subscribed_topics=subscribed_topics,
            received_messages=received_messages,
        ),
    )


@app.route("/power_system", methods=["GET", "POST"])  # type: ignore
@login_required
def power_system() -> ResponseReturnValue:
    """Handle Power System page showing BMS, MultiPlus data and power modes."""
    # Default thresholds (these match the ones in battery_monitor.py)
    default_thresholds = {"normal": 75, "eco": 50, "critical": 25}
    default_hysteresis = 5

    # Check if this is a request to send test data or update power mode config
    if request.method == "POST":
        form_type = request.form.get("form_type", "test_data")

        if form_type == "test_data":
            test_data_type = request.form.get("test_data_type", "all")

            # Create a test message with the current timestamp
            now_iso = datetime.now(timezone.utc).isoformat()
            device_payload = {
                "device": {
                    "timestamp": now_iso,
                }
            }

            # Add BMS data if requested
            if test_data_type == "all" or test_data_type == "bms":
                device_payload["device"]["bms"] = {
                    "volts": 48.2,
                    "amps": 15.7,
                    "watts": 756.74,
                    "remainingAh": 180.5,
                    "fullAh": 200.0,
                    "charging": True,
                    "temp": 32.5,
                    "stateOfCharge": 90.25,
                    "stateOfHealth": 98.5,
                    "iRSOC": 90,  # Adding integer state of charge
                }

            # Add MultiPlus data if requested
            if test_data_type == "all" or test_data_type == "multiplus":
                device_payload["device"]["multiPlus"] = {
                    "voltsIn": 230.5,
                    "ampsIn": 4.2,
                    "wattsIn": 968.1,
                    "freqIn": 50.02,
                    "voltsOut": 230.0,
                    "ampsOut": 3.8,
                    "wattsOut": 874.0,
                    "freqOut": 50.0,
                }

            # Publish the test data to MQTT
            try:
                client = mqtt.Client(protocol=mqtt.MQTTv5)
                client.connect(os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto"), 1883)

                result = client.publish("out/device", json.dumps(device_payload), qos=1)

                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    flash("Test data published successfully", "success")
                else:
                    flash(
                        f"Failed to publish test data: {mqtt.error_string(result.rc)}",
                        "error",
                    )

                client.disconnect()
            except Exception as e:
                flash(f"Error publishing test data: {str(e)}", "error")

        elif form_type == "power_mode_config":
            try:
                # Get values from form
                normal_threshold = int(
                    request.form.get("normal_threshold", default_thresholds["normal"])
                )
                eco_threshold = int(
                    request.form.get("eco_threshold", default_thresholds["eco"])
                )
                critical_threshold = int(
                    request.form.get(
                        "critical_threshold", default_thresholds["critical"]
                    )
                )
                hysteresis = int(request.form.get("hysteresis", default_hysteresis))

                # Validate values
                if not (
                    0 <= critical_threshold < eco_threshold < normal_threshold <= 100
                ):
                    flash(
                        "Invalid thresholds. Ensure Normal > Eco > Critical and all values are 0-100%.",
                        "error",
                    )
                elif not (0 <= hysteresis <= 20):
                    flash(
                        "Invalid hysteresis. Value must be between 0 and 20%.", "error"
                    )
                else:
                    # TODO: Save updated thresholds to configuration
                    # This is a placeholder for future implementation
                    # Update the battery_monitor.py module with the new thresholds

                    # Create a message to publish updated power mode configuration
                    power_config = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "thresholds": {
                            "normal": normal_threshold,
                            "eco": eco_threshold,
                            "critical": critical_threshold,
                        },
                        "hysteresis": hysteresis,
                    }

                    try:
                        # Publish the updated config to MQTT for the battery monitor to pick up
                        client = mqtt.Client(protocol=mqtt.MQTTv5)
                        client.connect(
                            os.environ.get("MQTT_BROKER_ADDRESS", "mosquitto"), 1883
                        )

                        result = client.publish(
                            "system/power_config",
                            json.dumps(power_config),
                            qos=1,
                            retain=True,
                        )

                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            flash(
                                "Power mode configuration updated successfully!",
                                "success",
                            )
                        else:
                            flash(
                                f"Failed to update power configuration: {mqtt.error_string(result.rc)}",
                                "error",
                            )

                        client.disconnect()
                    except Exception as e:
                        flash(
                            f"Error publishing power configuration: {str(e)}", "error"
                        )

            except ValueError:
                flash("Invalid input. Please enter numeric values.", "error")

    # Get the latest BMS data
    latest_bms = None
    bms_history = []
    with SessionLocal() as db_session:
        latest_bms_record = (
            db_session.query(BMSData).order_by(desc(BMSData.timestamp)).first()
        )
        if latest_bms_record:
            latest_bms = latest_bms_record

        # Get BMS history (last 10 records)
        bms_history = (
            db_session.query(BMSData).order_by(desc(BMSData.timestamp)).limit(10).all()
        )

    # Get the latest MultiPlus data
    latest_multiplus = None
    multiplus_history = []
    with SessionLocal() as db_session:
        latest_multiplus_record = (
            db_session.query(MultiPlusData)
            .order_by(desc(MultiPlusData.timestamp))
            .first()
        )
        if latest_multiplus_record:
            latest_multiplus = latest_multiplus_record

        # Get MultiPlus history (last 10 records)
        multiplus_history = (
            db_session.query(MultiPlusData)
            .order_by(desc(MultiPlusData.timestamp))
            .limit(10)
            .all()
        )

    # Get current power mode based on the latest BMS data
    current_mode = "unknown"
    battery_level = 0
    last_updated = None

    # Determine power mode based on latest BMS data
    if latest_bms:
        # Use integer_soc if available, otherwise use state_of_charge
        battery_level = (
            latest_bms.integer_soc
            if latest_bms.integer_soc is not None
            else int(latest_bms.state_of_charge)
        )

        # Determine mode based on battery level (simplified without hysteresis)
        if battery_level >= default_thresholds["normal"]:
            current_mode = "normal"
        elif battery_level >= default_thresholds["eco"]:
            current_mode = "eco"
        elif battery_level >= default_thresholds["critical"]:
            current_mode = "critical"
        else:
            current_mode = "emergency"

        last_updated = latest_bms.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    return cast(
        ResponseReturnValue,
        render_template(
            "power_system.html",
            latest_bms=latest_bms,
            latest_multiplus=latest_multiplus,
            bms_history=bms_history,
            multiplus_history=multiplus_history,
            current_mode=current_mode,
            battery_level=battery_level,
            last_updated=last_updated,
            thresholds=default_thresholds,
            hysteresis=default_hysteresis,
        ),
    )


@app.route("/power_system_modes", methods=["GET", "POST"])  # type: ignore
@login_required
def power_system_modes() -> ResponseReturnValue:
    """Display and manage power system modes based on battery levels.

    Returns:
        ResponseReturnValue: The rendered template with power system mode information
    """
    # Default thresholds (these match the ones in battery_monitor.py)
    default_thresholds = {"normal": 75, "eco": 50, "critical": 25}
    default_hysteresis = 5

    # If POST request, update the configuration
    if request.method == "POST":
        try:
            # Get values from form
            normal_threshold = int(
                request.form.get("normal_threshold", default_thresholds["normal"])
            )
            eco_threshold = int(
                request.form.get("eco_threshold", default_thresholds["eco"])
            )
            critical_threshold = int(
                request.form.get("critical_threshold", default_thresholds["critical"])
            )
            hysteresis = int(request.form.get("hysteresis", default_hysteresis))

            # Validate values
            if not (0 <= critical_threshold < eco_threshold < normal_threshold <= 100):
                flash(
                    "Invalid thresholds. Ensure Normal > Eco > Critical and all values are 0-100%.",
                    "danger",
                )
            elif not (0 <= hysteresis <= 20):
                flash("Invalid hysteresis. Value must be between 0 and 20%.", "danger")
            else:
                # TODO: Save updated thresholds to configuration
                # This is a placeholder for future implementation
                # Update the battery_monitor.py module with the new thresholds
                # For now, we'll just show a success message
                flash("Power mode configuration updated successfully!", "success")

        except ValueError:
            flash("Invalid input. Please enter numeric values.", "danger")

    # Get the latest BMS data
    latest_bms = None
    with SessionLocal() as session:
        latest_bms = session.query(BMSData).order_by(desc(BMSData.timestamp)).first()

    # Get current power mode from MQTT (if available)
    current_mode = "unknown"
    battery_level = 0
    last_updated = None

    # TODO: In a future implementation, retrieve the current power mode from stored MQTT message
    # For now, determine it based on the latest BMS data if available
    if latest_bms:
        # Use integer_soc if available, otherwise use state_of_charge
        battery_level = (
            latest_bms.integer_soc
            if latest_bms.integer_soc is not None
            else int(latest_bms.state_of_charge)
        )

        # Determine mode based on battery level (simplified without hysteresis)
        if battery_level >= default_thresholds["normal"]:
            current_mode = "normal"
        elif battery_level >= default_thresholds["eco"]:
            current_mode = "eco"
        elif battery_level >= default_thresholds["critical"]:
            current_mode = "critical"
        else:
            current_mode = "emergency"

        last_updated = latest_bms.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    return cast(
        ResponseReturnValue,
        render_template(
            "power_system_modes.html",
            latest_bms=latest_bms,
            current_mode=current_mode,
            battery_level=battery_level,
            last_updated=last_updated,
            thresholds=default_thresholds,
            hysteresis=default_hysteresis,
        ),
    )


@app.route("/static/<path:filename>")  # type: ignore
def static_files(filename: str) -> Response:
    """Serve static files.

    Args:
        filename: The requested filename

    Returns:
        Response: The static file response
    """
    return send_from_directory("static", filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)

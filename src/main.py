"""Main process manager for the Hurtec integration system.

This module manages the lifecycle of all subprocesses including the web application,
MQTT broker, and background tasks. It handles graceful shutdown and process monitoring.
"""

import subprocess
import threading
import time
import logging
import signal
from typing import Any, List, Dict
import logger_setup
import config_util

logger_setup.set_process_name("main")

shutdown_flag = threading.Event()


def signal_handler(_sig: int, _frame: Any) -> None:
    """Handle shutdown signals."""
    logging.info("Shutdown signal received, stopping processes...")
    shutdown_flag.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def monitor_process(
    name: str,
    command: str,
    stop_event: threading.Event,
    restart_delay: int = 5,
    max_restart_delay: int = 1800,
    health_check_interval: int = 300,
) -> None:
    """
    Monitor and restart a process until shutdown is requested.

    Args:
        name: Name of the process for logging
        command: The command to run the process
        stop_event: Event that signals when to stop monitoring
        restart_delay: Initial delay in seconds before restarting (exponential backoff applies)
        max_restart_delay: Maximum delay in seconds before restarting (default: 30 minutes)
        health_check_interval: How often to check if process needs forced restart (default: 5 minutes)
    """
    current_delay = restart_delay  # Tracks the current delay before restarting a process, with exponential backoff.
    consecutive_failures = 0  # Counts consecutive failures to adjust the backoff delay.

    while not stop_event.is_set():
        logging.info("Starting %s: %s", name, command)
        start_time = time.time()

        with subprocess.Popen(command, shell=True) as proc:
            # Monitor the process with periodic health checks
            while proc.poll() is None and not stop_event.is_set():
                # Sleep for a short interval to check both health and shutdown flag
                time.sleep(5)

                # If process has been running for a long time, consider it healthy and reset backoff
                if time.time() - start_time > health_check_interval:
                    if consecutive_failures > 0:
                        logging.info(
                            "%s has been stable for %d seconds, resetting backoff timer.",
                            name,
                            health_check_interval,
                        )
                        consecutive_failures = 0
                        current_delay = restart_delay

            ret_code = proc.returncode

            if stop_event.is_set():
                logging.info("%s terminated due to shutdown signal.", name)
                break

            # Process exited on its own
            run_duration = time.time() - start_time

            if ret_code != 0:
                consecutive_failures += 1
                # Apply exponential backoff with maximum cap
                current_delay = min(current_delay * 2, max_restart_delay)

                logging.error(
                    "%s exited with error code %d after running for %.1f seconds. "
                    "Consecutive failures: %d. Restarting in %d seconds...",
                    name,
                    ret_code,
                    run_duration,
                    consecutive_failures,
                    current_delay,
                )
                time.sleep(current_delay)
            else:
                logging.info(
                    "%s exited normally after running for %.1f seconds.",
                    name,
                    run_duration,
                )
                # Reset backoff for clean exits
                consecutive_failures = 0
                current_delay = restart_delay
                time.sleep(current_delay)

    logging.info("%s monitor exiting.", name)


def main() -> None:
    """Main function to manage all processes."""
    # Log mock mode status
    if config_util.is_mock_mode():
        logging.info("Starting in MOCK MODE - external services will be simulated")
    else:
        logging.info("Starting in NORMAL MODE - connecting to real services")

    processes: List[Dict[str, str]] = [
        {"name": "MQTT Broker", "command": "python mqtt_broker.py"},
        {"name": "Background Task", "command": "python background_task.py"},
        {
            "name": "Web App",
            "command": "python web_app.py",
        },
    ]

    threads: List[threading.Thread] = []
    for proc in processes:
        thread = threading.Thread(
            target=monitor_process, args=(proc["name"], proc["command"], shutdown_flag)
        )
        thread.daemon = True
        thread.start()
        threads.append(thread)

    try:
        while not shutdown_flag.is_set():
            time.sleep(5)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received, shutting down...")
        shutdown_flag.set()

    # Wait for threads to finish
    for thread in threads:
        thread.join()
    logging.info("All services terminated. Exiting.")


if __name__ == "__main__":
    main()

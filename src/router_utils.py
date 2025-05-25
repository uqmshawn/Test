"""Utilities for working with the Peplink router API."""

import logging
import requests


def router_login(
    router_ip: str, router_userid: str, router_password: str
) -> requests.Session:
    """Login to the router API and get a session."""
    sesh = requests.Session()
    payload = {"username": router_userid, "password": router_password}
    response = sesh.post(f"https://{router_ip}/api/login", json=payload, verify=False)
    logging.debug("Router login response: %s", response.text)
    if response.json().get("stat") == "ok":
        logging.info("Router login succeeded")
        return sesh
    raise RuntimeError("Router login failed")


def re_authenticate(router_ip: str, credentials: dict[str, str]) -> requests.Session:
    """Re-authenticate with the router and get a new session."""
    logging.info("Attempting to re-authenticate...")
    try:
        new_session = router_login(
            router_ip,
            credentials["router_userid"],
            credentials["router_password"],
        )
        logging.info("Re-authenticated successfully")
        return new_session
    except Exception as auth_err:
        logging.error("Failed to re-authenticate: %s", auth_err)
        raise

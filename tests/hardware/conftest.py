"""Allow connections to the real lamp named by LAMP_HOST."""

from __future__ import annotations

import os

import pytest
import pytest_socket


@pytest.fixture(autouse=True)
def allow_lamp_host(socket_enabled: None) -> None:
    """Add the lamp to the hosts the Home Assistant harness lets tests reach."""
    host = os.environ.get("LAMP_HOST")
    if host:
        pytest_socket.socket_allow_hosts([host.split(":")[0], "127.0.0.1"])

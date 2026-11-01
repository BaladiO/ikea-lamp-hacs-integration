"""Constants for the IKEA OBEGRÄNSAD Lamp integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "obegraensad_lamp"
NAME: Final = "IKEA OBEGRÄNSAD Lamp"
MANUFACTURER: Final = "IKEA (ph1p firmware)"
MODEL: Final = "OBEGRÄNSAD 16×16"

# options
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_MESSAGE_DELAY: Final = "message_delay"
CONF_MESSAGE_REPEAT: Final = "message_repeat"
CONF_RESTORE: Final = "restore"
CONF_DDP_PORT: Final = "ddp_port"
CONF_MAX_LAMP_MESSAGES: Final = "max_lamp_messages"
CONF_NIGHT_SUPPRESS_LOW: Final = "night_suppress_low"

DEFAULT_POLL_INTERVAL: Final = 30
DEFAULT_MESSAGE_DELAY: Final = 50
DEFAULT_MESSAGE_REPEAT: Final = 0
DEFAULT_RESTORE: Final = True
DEFAULT_DDP_PORT: Final = 4048
DEFAULT_MAX_LAMP_MESSAGES: Final = 4
DEFAULT_NIGHT_SUPPRESS_LOW: Final = False

# plugin names the integration needs, resolved to ids at runtime
DDP_PLUGIN_NAME: Final = "DDP"

# raise a repair issue when the lamp has been unreachable this long (seconds)
UNREACHABLE_ISSUE_AFTER: Final = 30 * 60
ISSUE_UNREACHABLE: Final = "unreachable"
ISSUE_FIRMWARE: Final = "firmware_unsupported"

RESET_REASONS: Final = [
    "poweron",
    "external",
    "software",
    "panic",
    "int_wdt",
    "task_wdt",
    "wdt",
    "deepsleep",
    "brownout",
    "sdio",
    "unknown",
]

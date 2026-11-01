"""DDP (Distributed Display Protocol) frames for the lamp's DDP plugin.

The firmware skips a 10-byte header, averages each RGB triple into one
brightness value and turns values <= 4 off. Frames here are grey-scale, so
every pixel is sent as R = G = B. This module has no Home Assistant dependency.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import logging

_LOGGER = logging.getLogger(__name__)

DDP_PORT = 4048
DDP_HEADER = bytes([0x41]) + bytes(9)
# the firmware turns averaged values <= 4 off
MIN_VISIBLE = 5
DEFAULT_PIXELS = 256


def to_wire_value(value: int) -> int:
    """Clamp to 0-255 and lift faint lit pixels so the lamp shows them."""
    value = max(0, min(255, int(value)))
    if 0 < value < MIN_VISIBLE:
        return MIN_VISIBLE
    return value


def build_packet(frame: Sequence[int], pixels: int = DEFAULT_PIXELS) -> bytes:
    """Build a full-frame packet: header + ``pixels`` × RGB.

    ``frame`` is row-major brightness, one value per pixel.
    """
    if len(frame) != pixels:
        raise ValueError(f"frame must have {pixels} values, got {len(frame)}")
    payload = bytearray(pixels * 3)
    for index, value in enumerate(frame):
        wire = to_wire_value(value)
        payload[index * 3 : index * 3 + 3] = bytes((wire, wire, wire))
    return DDP_HEADER + bytes(payload)


def build_fill_packet(value: int) -> bytes:
    """Build a single-pixel packet, which the firmware spreads over the matrix."""
    wire = to_wire_value(value)
    return DDP_HEADER + bytes((wire, wire, wire))


class DdpSender:
    """Sends DDP packets to one lamp over a connected UDP socket."""

    def __init__(self, host: str, port: int = DDP_PORT) -> None:
        """Store the target; the socket opens on first use."""
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None

    async def open(self) -> None:
        """Open the UDP endpoint if it is not open yet."""
        if self._transport is not None and not self._transport.is_closing():
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, remote_addr=(self._host, self._port)
        )
        self._transport = transport

    async def send_packet(self, packet: bytes) -> None:
        """Send a prebuilt packet."""
        await self.open()
        assert self._transport is not None
        self._transport.sendto(packet)

    async def send_frame(self, frame: Sequence[int]) -> None:
        """Send a full frame."""
        await self.send_packet(build_packet(frame, len(frame)))

    async def fill(self, value: int) -> None:
        """Set every pixel to ``value``."""
        await self.send_packet(build_fill_packet(value))

    def close(self) -> None:
        """Close the socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

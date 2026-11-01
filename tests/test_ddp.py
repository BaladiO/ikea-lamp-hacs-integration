"""Tests for the DDP packet builder and sender."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.obegraensad_lamp.ddp import (
    DDP_HEADER,
    MIN_VISIBLE,
    DdpSender,
    build_fill_packet,
    build_packet,
    to_wire_value,
)


def firmware_decode(packet: bytes) -> list[int]:
    """What DDPPlugin.cpp makes of a full-frame packet."""
    data = packet[10:]
    out = []
    for i in range(len(data) // 3):
        value = (data[i * 3] + data[i * 3 + 1] + data[i * 3 + 2]) // 3
        out.append(value if value > 4 else 0)
    return out


def test_header() -> None:
    """Header is 0x41 followed by nine zero bytes."""
    assert bytes([0x41, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == DDP_HEADER


def test_full_frame_exact_bytes() -> None:
    """A full frame is 10 + 768 bytes, grey-scale RGB in row-major order."""
    frame = [0] * 256
    frame[0] = 255
    frame[17] = 128  # x=1, y=1
    packet = build_packet(frame)
    assert len(packet) == 778
    assert packet[:10] == DDP_HEADER
    assert packet[10:13] == bytes([255, 255, 255])
    assert packet[10 + 17 * 3 : 10 + 18 * 3] == bytes([128, 128, 128])
    assert packet[13:16] == bytes(3)
    assert firmware_decode(packet) == frame


@pytest.mark.parametrize("value", [1, 2, 3, 4])
def test_faint_pixels_stay_visible(value: int) -> None:
    """Values the firmware would turn off are lifted to the minimum visible."""
    assert to_wire_value(value) == MIN_VISIBLE
    frame = [value] * 256
    assert set(firmware_decode(build_packet(frame))) == {MIN_VISIBLE}


def test_no_lit_value_below_threshold() -> None:
    """No byte in a packet is in the 1-4 range."""
    packet = build_packet(list(range(256)))
    assert not any(1 <= b <= 4 for b in packet[10:])


def test_clamping() -> None:
    """Out-of-range values are clamped."""
    assert to_wire_value(-5) == 0
    assert to_wire_value(999) == 255


def test_wrong_size() -> None:
    """Frames of the wrong size are rejected."""
    with pytest.raises(ValueError):
        build_packet([0] * 255)


def test_fill_packet() -> None:
    """The single-pixel form has three payload bytes."""
    assert build_fill_packet(0) == DDP_HEADER + bytes(3)
    assert build_fill_packet(200) == DDP_HEADER + bytes([200, 200, 200])


@pytest.mark.enable_socket
async def test_sender_delivers_packets() -> None:
    """Packets arrive over UDP unchanged."""
    received: asyncio.Queue[bytes] = asyncio.Queue()

    class Receiver(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            received.put_nowait(data)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(Receiver, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    sender = DdpSender("127.0.0.1", port)
    try:
        frame = [10] * 256
        await sender.send_frame(frame)
        await sender.fill(0)
        assert await asyncio.wait_for(received.get(), 2) == build_packet(frame)
        assert await asyncio.wait_for(received.get(), 2) == build_fill_packet(0)
    finally:
        sender.close()
        transport.close()

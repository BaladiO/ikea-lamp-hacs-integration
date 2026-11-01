"""Manual test tool for the lamp, using the integration's own client code.

Only needs aiohttp; Home Assistant is not imported.

    python scripts/lampctl.py --host 192.168.100.45 info
    python scripts/lampctl.py frame
    python scripts/lampctl.py watch --seconds 30
    python scripts/lampctl.py plugin Weather
    python scripts/lampctl.py brightness 128
    python scripts/lampctl.py rotate right
    python scripts/lampctl.py message "HELLO" --id 101 --repeat 0
    python scripts/lampctl.py remove-message 101
    python scripts/lampctl.py ddp-fill 0 --hold 5 --restore
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import sys
import types
from typing import Any

import aiohttp

# Load the client modules without running the integration's __init__.py,
# which imports Home Assistant.
_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "obegraensad_lamp"
_pkg = types.ModuleType("obegraensad_lamp")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules["obegraensad_lamp"] = _pkg
api = importlib.import_module("obegraensad_lamp.api")
ddp = importlib.import_module("obegraensad_lamp.ddp")
ws_client = importlib.import_module("obegraensad_lamp.ws_client")


def print_frame(frame: bytes | list[int], cols: int = 16) -> None:
    """Draw a frame as text, one character per pixel."""
    shades = " .:-=+*#%@"
    for y in range(len(frame) // cols):
        row = frame[y * cols : (y + 1) * cols]
        print("".join(shades[min(9, v * 10 // 256)] * 2 for v in row))


async def run(args: argparse.Namespace) -> int:
    """Execute one command."""
    async with aiohttp.ClientSession() as session:
        client = api.LampClient(session, args.host)
        cmd = args.command

        if cmd == "info":
            state = await client.get_info()
            data = {k: v for k, v in asdict(state).items() if k not in ("plugins", "frame")}
            data["plugin_name"] = state.plugin.name if state.plugin else None
            print(json.dumps(data, indent=2, default=str))
        elif cmd == "plugins":
            for plugin in (await client.get_info()).plugins:
                print(f"{plugin.id:3d}  {plugin.name}")
        elif cmd == "frame":
            print_frame(await client.get_frame())
        elif cmd == "watch":
            await watch(session, args.host, args.seconds)
        elif cmd == "plugin":
            state = await client.get_info()
            plugin = state.plugin_by_name(args.name)
            if plugin is None:
                print(f"unknown plugin {args.name!r}", file=sys.stderr)
                return 1
            await client.set_plugin(plugin.id)
        elif cmd == "brightness":
            await client.set_brightness(args.value)
        elif cmd == "rotate":
            await ws_send(session, args.host, {"event": "rotate", "direction": args.direction})
        elif cmd == "message":
            await client.send_message(
                args.text, message_id=args.id, repeat=args.repeat, delay=args.delay
            )
        elif cmd == "remove-message":
            await client.remove_message(args.id)
        elif cmd == "ddp-fill":
            await ddp_fill(client, args)
    return 0


async def ws_send(session: aiohttp.ClientSession, host: str, payload: dict[str, Any]) -> None:
    """Open the socket, send one event, wait for the resulting info push."""
    got = asyncio.Event()
    infos: list[dict[str, Any]] = []

    def on_info(data: dict[str, Any]) -> None:
        infos.append(data)
        if len(infos) >= 2:
            got.set()

    sock = ws_client.LampWebSocket(session, host, on_info)
    sock.start()
    try:
        for _ in range(100):
            if sock.connected:
                break
            await asyncio.sleep(0.05)
        await sock.send(payload)
        await asyncio.wait_for(got.wait(), 5)
        print(f"rotation={infos[-1]['rotation']} plugin={infos[-1]['plugin']}")
    finally:
        await sock.stop()


async def watch(session: aiohttp.ClientSession, host: str, seconds: float) -> None:
    """Print every info push for a while."""

    def on_info(data: dict[str, Any]) -> None:
        data = {k: v for k, v in data.items() if k not in ("data", "plugins")}
        print(json.dumps(data))

    sock = ws_client.LampWebSocket(session, host, on_info, lambda c: print("connected:", c))
    sock.start()
    await asyncio.sleep(seconds)
    await sock.stop()


async def ddp_fill(client: Any, args: argparse.Namespace) -> None:
    """Switch to DDP, fill the matrix, hold, optionally restore the plugin."""
    state = await client.get_info()
    previous = state.plugin
    ddp_plugin = state.plugin_by_name("DDP")
    if ddp_plugin is None:
        raise SystemExit("lamp has no DDP plugin")
    sender = ddp.DdpSender(client.host.split(":")[0])
    try:
        await client.set_plugin(ddp_plugin.id)
        end = asyncio.get_running_loop().time() + args.hold
        while asyncio.get_running_loop().time() < end:
            await sender.fill(args.value)
            await asyncio.sleep(1)
    finally:
        sender.close()
        if args.restore and previous is not None:
            await client.set_plugin(previous.id)
            print(f"restored {previous.name}")


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--host", default=os.environ.get("LAMP_HOST", "192.168.100.45"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info")
    sub.add_parser("plugins")
    sub.add_parser("frame")
    p = sub.add_parser("watch")
    p.add_argument("--seconds", type=float, default=30)
    p = sub.add_parser("plugin")
    p.add_argument("name")
    p = sub.add_parser("brightness")
    p.add_argument("value", type=int)
    p = sub.add_parser("rotate")
    p.add_argument("direction", choices=["left", "right"])
    p = sub.add_parser("message")
    p.add_argument("text")
    p.add_argument("--id", type=int, default=100)
    p.add_argument("--repeat", type=int, default=0)
    p.add_argument("--delay", type=int, default=50)
    p = sub.add_parser("remove-message")
    p.add_argument("id", type=int)
    p = sub.add_parser("ddp-fill")
    p.add_argument("value", type=int)
    p.add_argument("--hold", type=float, default=5)
    p.add_argument("--restore", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

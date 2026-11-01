# Progress

## Phase 1: Recon (done, 2026-11-01)

- Read the firmware at `6d6ffff` (2026-10-18): `asyncwebserver.cpp`, `webhandler.cpp`,
  `websocket.cpp`, `messages.cpp`, `DDPPlugin.cpp`, `PluginManager.cpp`,
  `scheduler.cpp`, `brightness_schedule.cpp`, `signs.cpp`, `constants.h`.
- Probed the lamp read-only: `/api/info`, `/api/data`, `/api/config`, a 404 route
  and a 5 s WebSocket listen. Results are in [lamp-api.md](lamp-api.md).
- Lamp baseline at the start: plugin 37 (Weather), rotation 0, brightness 255, boot
  plugin 12 (Spiral), plugin schedule empty, night schedule off, ~104 kB free heap.

### Design consequences

- Diagnostics (rssi, uptime, heap) are not in the WS push, so the HTTP poll also
  feeds those sensors.
- The WS client sends `live-preview: false` right after connecting.
- After an HTTP plugin/brightness change, the integration asks for an `info` push
  (or uses the WS command when the socket is up).
- A running plugin schedule would switch away from DDP in the middle of a temporary
  display, so the engine stops the schedule first and starts it again after the
  restore (it restarts at the first entry; the firmware has no resume).
- The notify queue limits messages on the lamp itself, because a full pool fails
  silently, and gives each message a distinct id, because id 0 replaces id 0.
- Messages need a synced lamp clock and repeat once per minute; documented for users.
- Every plugin switch flashes the plugin id for 800 ms, which is visible when a
  temporary display starts and ends. This cannot be avoided without firmware changes.

## Phase 2: Core client

Not started.

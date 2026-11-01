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

## Phase 2: Core client (done, 2026-11-01)

- `api.py` (HTTP client, typed errors, serialised requests with 100 ms gap, retries on
  connection errors), `ws_client.py` (one socket, live-preview opt-out, backoff to
  60 s), `ddp.py` (packet builder, UDP sender). None of them import Home Assistant.
- `tests/fake_lamp.py` mimics the firmware for tests. 30 tests, coverage api 96 %,
  ddp 100 %, ws_client 94 %. ruff and mypy --strict clean.
- `scripts/lampctl.py` for manual checks.

Verified on the real lamp:

- `info`, `frame`, `watch` via the CLI.
- DDP: switched to plugin DDP (the switch takes ~1 s including the 800 ms id
  display), sent a full frame over UDP, read `/api/data` back: byte-exact match,
  including a faint value 3 shown as 5. `fill(0)` blanks the matrix. Restored Weather.
- `/api/message` with id 101: the text scrolled (6 distinct frames in 3 s), so the
  lamp clock is synced. Removed afterwards.
- Free heap went from 103 920 to 98 948 bytes over these switches. To be watched in
  the soak test (Weather re-fetches its data after every re-activation).

## Phase 3: Integration skeleton (done, 2026-11-01)

- Manifest, config flow (user, reconfigure with same-MAC check, options), coordinator,
  device (identifiers = MAC), light, plugin select, rotate/persist buttons, plugin and
  night schedule switches, night brightness number, start/end time entities,
  diagnostic sensors, connectivity binary sensor, repair issues (long outage,
  missing `/api/info`), services `select_plugin`, `set_brightness_schedule`,
  `set_plugin_schedule`.
- Coordinator: WebSocket pushes update the state at once and entities debounced
  (200 ms); pushes do not reset the 30 s poll, which is the only source of the
  diagnostics. Commands use the WebSocket when it is up and HTTP + a poll otherwise.
- Tests run in Docker (`python:3.14-slim` + `pytest-homeassistant-custom-component
  0.13.346` = Home Assistant 2026.7.2), the same version as the user's install.
  55 tests pass; ruff and mypy --strict are clean.
- Choice: the brief gives both 30 s (5.1) and 60 s (5.7) as poll default; 30 s was
  taken so the diagnostic sensors stay fresh. One small GET every 30 s is light.

## Phase 4: Notifications (done, 2026-11-01)

- `text.py`: sanitiser built from the font table in `signs.cpp`. Keeps ASCII 32-126
  and Ä Ö Ü ß ä ö ü, maps arrows to the font's arrow glyphs, transliterates accents
  (é → e) and typographic characters, drops emoji and unsupported scripts (e.g.
  Arabic), collapses whitespace, cuts at 160 characters. Changes are logged at debug.
- `messages.py`: queue in front of the lamp's pool. At most N messages on the lamp
  (option, default 4, capped at 8 of the 10 slots), up to 20 more wait in Home
  Assistant, then a clear "queue full" error. Ids: automatic 1-999, numeric
  `message_id` n → 1000 + n, text ids hashed into their own range, so the same
  `message_id` always replaces/removes the same message. Each slot gets an
  upper-bound lifetime (scroll time + repeats × 60 s + 10 s); at that point the
  message is removed explicitly, which also covers a lamp whose clock never synced.
  High priority jumps the queue and may push out the oldest normal finite message;
  low priority can be dropped while the night brightness is active (option).
- `notify` entity (`notify.send_message`, title → `TITLE: message`), services
  `send_message` (with response: status sent/queued/suppressed and lamp id) and
  `remove_message` (by id, or all).
- Test note: `async_fire_time_changed` also fires aiohttp's internal timeout timers,
  which broke real-socket tests (a retried request, then an early expiry), and
  `freezer` stalls real I/O. The expiry test therefore shrinks the timing constants
  and runs in real time instead.
- 82 tests pass (two runs back to back), ruff and mypy --strict clean.

## Phase 5: Display engine

Not started.

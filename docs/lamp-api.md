# Lamp API reference (verified)

This is the interface of the IKEA OBEGRÄNSAD lamp running
[ph1p/ikea-led-obegraensad](https://github.com/ph1p/ikea-led-obegraensad), as the
integration relies on it. It was written from the firmware source at commit
`6d6ffff` (2026-10-18) and checked with read-only probes against the real lamp
(ESP32, `192.168.100.45`) on 2026-11-01.

Where this page and the firmware README disagree, this page follows the source.
The differences are listed at the end.

## Display model

- 16×16 matrix, monochrome, 8-bit brightness per pixel. `rows`/`cols` are reported
  by `/api/info`.
- Row-major, index = `y * 16 + x`, x = column 0–15, y = row 0–15.
- Rotation 0–3 in quarter turns, applied by the firmware to everything it draws.
- Every plugin switch first draws the plugin's id as digits for **800 ms**
  (`PluginManager::renderPluginId`), unless the plugin schedule is active. The HTTP
  request that switched the plugin blocks for that time.

## System status

`status` in `/api/info` and the WebSocket push is the `SYSTEM_STATUS` enum:
`0 NONE`, `1 WSBINARY`, `2 UPDATE`, `3 LOADING`. While a message scrolls the status is
`LOADING`, but no push is sent for that.

## HTTP API

All routes are plain HTTP on port 80 with no authentication. Error responses from
handlers are JSON `{"error": true, "message": "..."}`, success responses are
`{"status": "success", "message": "..."}` with HTTP 200. Unknown routes return
`404 text/plain` with body `Page not found!`. Typical latency is 25–50 ms.

| Method + path | Parameters | Success | Errors | Pushes WS `info`? |
|---|---|---|---|---|
| `GET /api/info` | – | full state JSON (below) | – | no |
| `PATCH /api/plugin` | query `id` (int) | 200 success | 422 `Could not set plugin to id N` | **no** |
| `PATCH /api/brightness` | query `value` 0–255 | 200 success | 422 when out of range | **no** |
| `PUT /api/brightness-schedule` | JSON body, see below | 200 `{"baseBrightness","brightness","brightnessSchedule":{...}}` | 400 invalid JSON, 422 invalid config, 422 start == end | yes |
| `GET /api/data` | – | 256 raw bytes, `application/octet-stream`, one brightness byte per pixel | – | no |
| `GET /api/message` | see below | 200 `Message received` | 422 bad `graph` or `maxy < miny` | no |
| `GET /api/removemessage` | query `id` (int) | 200 `Message removed` (also when the id did not exist) | – | no |
| `POST /api/schedule` | form field `schedule` = JSON array of `{"pluginId":int,"duration":seconds}` | 200 `Schedule updated`, **and the schedule is started** | 400 `Schedule cannot be set` (empty or invalid JSON) | yes |
| `GET /api/schedule/start` | – | 200 | 404 `No schedule found` when empty | yes |
| `GET /api/schedule/stop` | – | 200 | 404 `No schedule found` when empty | yes |
| `GET /api/schedule/clear` | – | 200, clears stored schedule too | – | yes |
| `GET /api/config` | – | `{"weatherLocation","ntpServer","tzInfo","autoStartSchedule"}` | 500 | no |
| `POST /api/config` | JSON body with any of the config keys | 200 | 400, 500 | no |
| `GET /api/storage/clear` | – | **destructive, never called** | | |
| `POST /api/config/reset` | – | **destructive, never called** | | |
| `/update` | – | OTA, **out of scope, never touched** | | |

Parameters are read with Arduino `toInt()`, so a missing or non-numeric value
silently becomes `0`.

### `GET /api/info`

Observed on the real lamp:

```json
{"rows":16,"cols":16,"status":0,"plugin":37,"rotation":0,"baseBrightness":255,"brightness":255,
 "brightnessSchedule":{"enabled":false,"startTime":"22:00","endTime":"07:00","brightness":20,"active":false},
 "scheduleActive":false,"rssi":-66,"uptime":1356,"freeHeap":103844,
 "ipAddress":"192.168.100.45","macAddress":"E8:6B:EA:C4:41:F0","resetReason":"poweron",
 "schedule":[],"plugins":[{"id":1,"name":"Draw"}, "..."]}
```

- `baseBrightness` is the user setting, `brightness` the brightness currently shown
  (lower while the night schedule is active).
- `uptime` is in seconds (`millis()/1000`, wraps after ~49.7 days).
- `resetReason` is one of `poweron`, `external`, `software`, `panic`, `int_wdt`,
  `task_wdt`, `wdt`, `deepsleep`, `brownout`, `sdio`, `unknown`.
- `schedule[].duration` is in seconds.
- Plugin ids are assigned in registration order, so they depend on the build. The
  integration always resolves plugins **by name**. On this lamp:
  1 Draw … 37 Weather, 38 Animation, 39 DDP, 40 ArtNet.

### `GET /api/message`

| Query | Meaning |
|---|---|
| `text` | Text to scroll. Bytes are drawn with the system font, see *Font*. |
| `repeat` | Extra showings after the first one. `0` = shown once, `1` = twice, `-1` = forever. |
| `id` | Integer id. **Adding a message first removes any message with the same id**, and a missing id is `0`, so every caller must pass distinct ids. |
| `delay` | ms per scroll step. `<= 0` becomes 50. |
| `graph` | Comma-separated ints, scrolled as a line graph after the text. |
| `miny`, `maxy` | Graph range. `maxy` 0 becomes 15. `maxy < miny` → 422. |

Behaviour (from `messages.cpp` and `main.cpp`):

- The pool holds **10** messages. When it is full the message is **silently dropped**
  and the route still answers 200 (`Warning: Message pool exhausted!` goes only to
  the serial log). The integration must track how many messages it has on the lamp.
- Messages are only shown when the lamp's clock is **NTP-synced**
  (`getSyncedLocalTime`), and only while `status == NONE`. A new message is shown
  straight away; repeats are shown **once per minute** (at each minute change), all
  active messages one after another.
- While any message is active, pixel (0,0) blinks once a second as an indicator.
- Scrolling blocks the screen task. One showing of text takes
  `(16 + 6 × glyph_count) × delay` ms; a graph takes `(16 + len(graph)) × delay` ms.
- There is no notification when a message finishes. The integration has to estimate
  this from the duration above.

### `PUT /api/brightness-schedule`

Body: `{"enabled": bool, "startTime": "HH:MM", "endTime": "HH:MM", "brightness": 0-255}`.
All four keys are required and must have these JSON types. Times are zero-padded,
may cross midnight, and must differ. The setting is persisted. It only takes effect
when the clock is synced.

## WebSocket `ws://<host>/ws`

- On connect the lamp sends one `info` text frame **and subscribes the client to the
  binary live preview**: 256-byte binary frames up to 10 per second whenever the
  picture changes. The client must send `{"event":"live-preview","enabled":false}`
  right after connecting. Verified: one binary frame arrives before the opt-out, none
  after it.
- `info` frame keys: `event` (`"info"`), `status`, `plugin`, `persist-plugin`
  (the plugin the lamp boots into, 12 = Spiral on this lamp), `rotation`,
  `baseBrightness`, `brightness`, `brightnessSchedule`, `scheduleActive`, `schedule`,
  `plugins`, `data` (256 ints). It does **not** contain `rssi`, `uptime`,
  `freeHeap`, `ipAddress`, `macAddress`, `resetReason`, `rows` or `cols`; those
  come from `/api/info` only.
- `info` is pushed to all clients after: WS commands below, schedule changes and
  scheduled plugin switches, the brightness schedule turning on/off, and the hardware
  button. It is **not** pushed after the HTTP plugin and brightness routes or
  messages.

Client → server text frames (`event` is required; anything else is ignored):

| Frame | Effect |
|---|---|
| `{"event":"plugin","plugin":id}` | Selects the plugin **and stops the plugin schedule** (in memory, the stored schedule stays). |
| `{"event":"persist-plugin"}` | Stores the active plugin as the boot plugin. |
| `{"event":"rotate","direction":"left"\|"right"}` | Rotates a quarter turn. Only way to rotate. |
| `{"event":"info"}` | Requests an `info` push. |
| `{"event":"live-preview","enabled":bool}` | Subscribes or unsubscribes the binary preview. |
| `{"event":"brightness","brightness":n}` | Sets base brightness (no range error; cast to uint8). |
| `{"event":"brightness-schedule", ...}` | Same body as the PUT, errors are ignored silently. |

The active plugin also sees every frame (`websocketHook`), e.g. the Draw plugin.

## DDP (UDP 4048)

- Only active while the plugin named `DDP` is selected. The port is fixed at 4048 in
  the firmware.
- Any packet of ≥ 10 bytes is accepted; the first 10 bytes are skipped without
  checking them. The integration sends the standard header `0x41` + 9 zero bytes.
- Payload is RGB triples. 3 bytes fill the whole matrix with one value; otherwise
  up to 256 triples map to pixels in order. A full frame is 768 payload bytes.
- Each pixel becomes `(R+G+B)/3`, and values `<= 4` become 0. The integration sends
  R=G=B=value and never uses 1–4 for a lit pixel.
- The last frame stays until another packet arrives or the plugin changes. There is
  no timeout.

## Font

`scrollText` uses the 5×7 system font (`signs.cpp`), offset 32, 157 glyphs:

- Codes 32–125: printable ASCII including lowercase.
- `~` (126) draws a right arrow, DEL (127) a left arrow.
- `Ä Ö Ü ß ä ö ü`: sent as UTF-8; the firmware skips the `0xC3` lead byte and uses
  the second byte as the glyph (132, 150, 156, 159, 164, 182, 188).
- Every other byte is drawn as a blank. Other multi-byte UTF-8 characters therefore
  produce blanks or wrong glyphs, so the integration transliterates them first.

## Differences from the firmware README and the build brief

| Item | Documented | Actual (source + lamp) |
|---|---|---|
| `GET /api/status` | listed as a working route in the brief | **does not exist**, returns 404 |
| Clear storage route | README: `/api/clearstorage` | `/api/storage/clear` |
| Config update | brief: `PATCH/PUT /api/config` | `POST /api/config` only |
| `/api/data` format | brief: digit string | 256 raw bytes, `application/octet-stream` |
| Message pool full | brief: firmware returns an error | silently dropped, 200 returned |
| DDP plugin id | README example: 17 | 39 on this build (ids are build-dependent) |
| Live preview | brief: "leave disabled" | enabled by default on connect, must be turned off |
| Message display | – | repeats only once per minute, and only with a synced clock |
| WS `plugin` event | – | also stops the plugin schedule; the HTTP route does not |
| HTTP plugin/brightness routes | – | do not push a WS `info` update |
| README Home Assistant example | `url: .../api/brightness/` | trailing slash is a different route and returns 404 |

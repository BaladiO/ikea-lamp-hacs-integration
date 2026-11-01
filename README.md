# IKEA OBEGRÄNSAD Lamp for Home Assistant

Control an IKEA OBEGRÄNSAD 16×16 LED wall lamp that runs the
[ph1p/ikea-led-obegraensad](https://github.com/ph1p/ikea-led-obegraensad) ESP32
firmware: brightness, plugins, rotation, schedules, **scrolling notifications**
and **temporary pictures** (icons, numbers, graphs) that put the lamp back to
what it was showing afterwards.

Everything is local: plain HTTP, a WebSocket and UDP on your LAN. No cloud, no
account, no token.

- [Requirements](#requirements)
- [Installation](#installation)
- [Setup](#setup)
- [Entities](#entities)
- [Notifications](#notifications)
- [Pictures, icons and graphs](#pictures-icons-and-graphs)
- [Automation examples](#automation-examples)
- [Service reference](#service-reference)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

## Requirements

- Home Assistant 2025.1 or newer (tested on 2026.7.2).
- [HACS](https://hacs.xyz).
- The lamp flashed with a current build of ph1p/ikea-led-obegraensad (one that
  has the `/api/info` route and the DDP plugin, i.e. 2025 or later).
- The lamp and Home Assistant on the same network. Give the lamp a **DHCP
  reservation** (a fixed IP address) in your router.

## Installation

1. In Home Assistant open **HACS**.
2. Open the menu (⋮, top right) → **Custom repositories**.
3. Repository: `https://github.com/BaladiO/ikea-lamp-hacs-integration`,
   type: **Integration** → **Add**.
4. Search HACS for **IKEA OBEGRÄNSAD Lamp**, open it, **Download**, and pick the
   latest version.
5. Restart Home Assistant (**Settings → System → Restart**).

Manual install: copy `custom_components/obegraensad_lamp` into your
`config/custom_components/` folder and restart.

## Setup

**Settings → Devices & services → Add integration → IKEA OBEGRÄNSAD Lamp**, then
enter the lamp's IP address, for example `192.168.100.45`. The lamp is identified
by its MAC address, so it cannot be added twice.

If the address changes later, use **⋮ → Reconfigure** on the integration entry.

**Options** (⋮ → Configure on the entry):

| Option | Default | Meaning |
|---|---|---|
| Poll interval | 30 s | How often `/api/info` is read. Live changes arrive over the WebSocket; the poll refreshes the diagnostic sensors and notices outages. |
| Default scroll delay | 50 ms | Milliseconds per scroll step; lower is faster. |
| Default message repeat | 0 | Extra showings after the first, once per minute. `-1` repeats until removed. |
| Messages kept on the lamp at once | 4 | The lamp holds 10 messages and silently drops more; the rest wait in Home Assistant. |
| Restore the previous plugin | on | Default for `restore` of the picture services. |
| Drop low-priority notifications at night | off | While the lamp's own night brightness is active, `priority: low` messages are skipped. |
| DDP port | 4048 | Only change it for a modified firmware. |

## Entities

One device per lamp. Entity ids depend on the device name; the examples use the
default `ikea_obegransad_lamp`.

| Entity | Type | What it does |
|---|---|---|
| `light.ikea_obegransad_lamp` | light | On/off and brightness. The firmware cannot switch the LEDs off, so off = brightness 0; on returns to the last brightness. Attributes: `plugin`, `rotation`, `displayed_brightness`, `night_brightness_active`. |
| `select.ikea_obegransad_lamp_plugin` | select | Active plugin (Weather, Big Clock, Snake, …). The list comes from the lamp. Choosing one stops a running plugin schedule, like the lamp's web page does. |
| `notify.ikea_obegransad_lamp_message` | notify | Scrolls text, see [Notifications](#notifications). |
| `button.…_rotate_left`, `button.…_rotate_right` | button | Rotate the picture by a quarter turn. |
| `button.…_make_current_plugin_the_startup_plugin` | button (config) | The lamp starts with this plugin after a power cut. |
| `switch.…_plugin_schedule` | switch | Starts/stops the stored plugin rotation. Attribute `schedule` lists it. Set it with `obegraensad_lamp.set_plugin_schedule`. |
| `switch.…_night_brightness_schedule` | switch (config) | The lamp's own night dimming. |
| `time.…_night_brightness_start`, `time.…_night_brightness_end` | time (config) | Night window, may cross midnight. |
| `number.…_night_brightness` | number (config) | Brightness during the night window, 0-255. |
| `sensor.…_wi_fi_signal` | sensor (diagnostic) | RSSI in dBm. |
| `sensor.…_uptime` | sensor (diagnostic) | Time since the lamp booted. |
| `sensor.…_free_memory` | sensor (diagnostic) | Free heap in bytes. |
| `sensor.…_last_reset_reason` | sensor (diagnostic) | Power on, crash, watchdog, brownout, … |
| `sensor.…_ip_address` | sensor (diagnostic) | The lamp's address. |
| `binary_sensor.…_reachable` | connectivity (diagnostic) | Whether the lamp answers. Attribute `websocket` shows if the live connection is up. |

All entities except *Reachable* become unavailable while the lamp is offline and
recover on their own.

## Notifications

The simplest way is the standard notify action:

```yaml
action: notify.send_message
target:
  entity_id: notify.ikea_obegransad_lamp_message
data:
  title: Laundry        # optional, shown as "Laundry: done"
  message: done
```

For more control use `obegraensad_lamp.send_message`:

```yaml
action: obegraensad_lamp.send_message
data:
  text: BATH
  repeat: -1             # until removed; 0 = once, 2 = three times (once a minute)
  delay: 40              # ms per scroll step
  message_id: bathroom   # lets you replace or remove it later
  priority: high         # low | normal | high
```

Good to know:

- The lamp's font has upper and lower case letters, digits, punctuation and
  Ä Ö Ü ä ö ü ß. Other characters are transliterated (é → e, → becomes an arrow)
  or dropped (emoji, Arabic script). Text longer than 160 characters is cut.
- Repeats are shown **once per minute**, at the minute change. That is how the
  firmware works.
- Messages only show when the lamp knows the time (NTP). Check the lamp's clock
  plugin if nothing appears.
- While messages are active, the top-left pixel blinks every second.
- Sending again with the same `message_id` replaces the message.
- The response of `send_message` tells you `sent`, `queued` or `suppressed`.

## Pictures, icons and graphs

These actions switch the lamp to its DDP plugin, draw a picture, and afterwards
return to the plugin it was showing (and restart a running plugin schedule). If
you or someone else changes the plugin in the meantime, the integration leaves it
alone. Each switch shows the plugin number on the lamp for under a second; that is
the firmware.

```yaml
action: obegraensad_lamp.show_icon
data:
  icon: door        # see the list below
  duration: 5
```

Built-in icons: `door`, `bell`, `shower`, `fan`, `light_bulb`, `warning`,
`check`, `cross`, `clock`, `wifi`, `thermometer`, `droplet`, `bolt`, `home`,
`person`, `arrow_up`, `arrow_down`, `arrow_left`, `arrow_right`, `heart`, `smiley`.

A number instead of an icon (up to 4 characters, digits `-` `.` `%`):

```yaml
action: obegraensad_lamp.show_icon
data:
  number: "{{ states('sensor.outdoor_temperature') | round(0) }}"
  duration: 10
```

Your own 16×16 picture: 16 rows of 16 hex digits (`0` off … `F` full):

```yaml
action: obegraensad_lamp.draw_frame
data:
  duration: 8
  rows:
    - "0000000000000000"
    - "000FF000000FF000"
    - "00FFFF0000FFFF00"
    - "0FFFFFF00FFFFFF0"
    - "0FFFFFFFFFFFFFF0"
    - "0FFFFFFFFFFFFFF0"
    - "00FFFFFFFFFFFF00"
    - "000FFFFFFFFFF000"
    - "0000FFFFFFFF0000"
    - "00000FFFFFF00000"
    - "000000FFFF000000"
    - "0000000FF0000000"
    - "0000000000000000"
    - "0000000000000000"
    - "0000000000000000"
    - "0000000000000000"
```

Without `duration`, `draw_frame` and `clear` keep the picture until another one
is shown, a message with `restore: true` arrives, or you call
`obegraensad_lamp.restore_display`.

Priorities: `high` interrupts what is shown, `normal` waits its turn, `low` waits
too, or is skipped with `drop_if_busy: true`.

## Automation examples

### Front door opened: door icon for 5 seconds

```yaml
alias: Lamp - front door
triggers:
  - trigger: state
    entity_id: binary_sensor.front_door   # your door sensor
    to: "on"
actions:
  - action: obegraensad_lamp.show_icon
    data:
      icon: door
      duration: 5
      priority: high
```

Or as text: `action: notify.send_message` with `message: DOOR`.

### Bathroom occupied too long: show BATH until it is free

```yaml
alias: Lamp - bathroom occupied
triggers:
  - trigger: state
    entity_id: binary_sensor.bathroom_presence
    to: "on"
    for: "00:20:00"
  - trigger: state
    entity_id: binary_sensor.bathroom_presence
    to: "off"
actions:
  - if:
      - condition: state
        entity_id: binary_sensor.bathroom_presence
        state: "on"
    then:
      - action: obegraensad_lamp.send_message
        data:
          text: BATH
          repeat: -1
          message_id: bathroom
    else:
      - action: obegraensad_lamp.remove_message
        data:
          message_id: bathroom
```

### Washing machine done

```yaml
alias: Lamp - washing machine done
triggers:
  - trigger: numeric_state
    entity_id: sensor.washing_machine_power
    below: 3
    for: "00:03:00"
actions:
  - action: obegraensad_lamp.send_message
    data:
      text: DONE
      repeat: 2
  - action: obegraensad_lamp.show_icon
    data:
      icon: check
      duration: 10
```

### Night: dim the lamp and keep it quiet

Use the lamp's own schedule (it keeps working when Home Assistant is down):

```yaml
action: obegraensad_lamp.set_brightness_schedule
data:
  enabled: true
  start: "22:30"
  end: "07:00"
  brightness: 15
```

Then enable **Drop low-priority notifications at night** in the options and send
unimportant messages with `priority: low`.

### Ambient: power use of the last 6 hours as a bar graph

```yaml
alias: Lamp - power graph every 15 minutes
triggers:
  - trigger: time_pattern
    minutes: "/15"
actions:
  - action: obegraensad_lamp.show_graph
    data:
      sensor: sensor.house_power
      hours: 6
      min: 0
      duration: 20
      priority: low
      drop_if_busy: true
```

Leave out `duration` to scroll it as a line graph with an optional `text` label.

### Gaming room scene

```yaml
actions:
  - action: obegraensad_lamp.select_plugin
    data:
      plugin: Space Invaders
  - action: cover.close_cover
    target:
      entity_id: cover.gaming_room_curtain
  - action: light.turn_on
    target:
      entity_id: light.gaming_room
```

## Service reference

All actions accept a device or entity target. With only one lamp configured the
target can be left out.

| Action | Fields |
|---|---|
| `obegraensad_lamp.send_message` | `text`, `repeat` (-1…1000), `delay` (ms), `message_id`, `graph` (list of numbers), `miny`, `maxy`, `priority` (low/normal/high), `restore` (end a held picture first, default true). Returns `status`, `message_id`, `lamp_id`. |
| `obegraensad_lamp.remove_message` | `message_id`, or `all: true`. Returns `removed`. |
| `obegraensad_lamp.show_icon` | `icon` or `number`, `duration` (default 5 s), `brightness` (5-255), `restore`, `priority`, `drop_if_busy`. |
| `obegraensad_lamp.draw_frame` | `rows` (16 × 16 hex) or `pixels` (256 values 0-255), `duration`, `restore`, `priority`, `drop_if_busy`. |
| `obegraensad_lamp.clear` | `duration`, `restore`, `priority`, `drop_if_busy`. |
| `obegraensad_lamp.show_graph` | `values` or `sensor` + `hours`, `min`, `max`, `duration` (bar graph) or `text` + `delay` (scrolling line graph), `restore`, `priority`, `drop_if_busy`. |
| `obegraensad_lamp.restore_display` | – (ends a held picture and restores the plugin). |
| `obegraensad_lamp.select_plugin` | `plugin` (name, case-insensitive). |
| `obegraensad_lamp.set_brightness_schedule` | `enabled`, `start`, `end`, `brightness`; fields left out stay as they are. |
| `obegraensad_lamp.set_plugin_schedule` | `action`: `set` (with `schedule`: list of `{plugin, duration}`), `start`, `stop`, `clear`. `set` starts the schedule right away (firmware behaviour). |

The picture services return `shown`, `queued` or `dropped`.

## Troubleshooting

**Cannot connect when adding the lamp.** Open `http://<lamp-ip>/` in a browser;
the lamp's web page must load. Check the IP in your router.

**"Firmware is too old" / repair issue.** The lamp has no `/api/info`. Flash the
current ph1p/ikea-led-obegraensad firmware.

**Lamp unavailable after a router restart.** Its IP probably changed. Make a DHCP
reservation, then **Reconfigure** the entry with the new address. After 30
minutes offline a repair issue is raised.

**Messages do not appear.** The lamp only scrolls text when its clock is set via
NTP (it needs internet access). Repeats are once per minute.

**Icons do not appear, the lamp just shows "39" briefly.** Pictures travel as UDP
packets to port 4048. Make sure nothing between Home Assistant and the lamp blocks
UDP (a guest network, client isolation, a firewall on the Home Assistant host).

**Rotate buttons fail.** Rotation exists only on the lamp's WebSocket; wait for
*Reachable* to show `websocket: true`.

**Diagnostics.** ⋮ → Download diagnostics on the device page gives the lamp's
state (IP and MAC redacted) to attach to an issue.

## Limitations

- The matrix is monochrome. There is no colour.
- The lamp cannot be switched off completely; off is brightness 0.
- Every plugin switch shows the plugin number for ~0.8 s (firmware), so pictures
  start and end with a short flash of digits.
- Restarting a plugin schedule after a picture starts it from its first entry.
- The lamp gives no feedback when a message has finished; the integration
  estimates it and removes the message explicitly afterwards.
- Messages put on the lamp by other tools count against its 10 slots but are not
  known to the integration.
- Messages with `repeat: -1` stay on the lamp across Home Assistant restarts.
  Give them a `message_id` so `remove_message` can find them again.
- The integration never flashes the firmware, never touches OTA, and never calls
  the lamp's storage-clear or config-reset routes.

## Development

```bash
# tests run against Home Assistant 2026.7.2 (Python 3.14)
pip install -r requirements_test.txt
pytest
# against a real lamp (visible but short, state is restored)
LAMP_HOST=192.168.100.45 pytest tests/hardware
# manual checks without Home Assistant
python scripts/lampctl.py --host 192.168.100.45 info
```

The verified lamp API is described in [docs/lamp-api.md](docs/lamp-api.md).

License: MIT.

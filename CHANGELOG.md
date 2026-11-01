# Changelog

## [0.1.0] - 2026-11-01

First release.

### Added

- Config flow by IP address, reconfigure, options (poll interval, message
  defaults, lamp message limit, restore default, night suppression, DDP port).
- Entities: light (brightness, off = 0), plugin select, rotate and startup-plugin
  buttons, plugin schedule and night schedule switches, night start/end times,
  night brightness, diagnostic sensors (Wi-Fi, uptime, free memory, reset reason,
  IP), reachability.
- Notify entity and `send_message` / `remove_message` with a queue in front of the
  lamp's 10-message pool, text transliteration for the lamp font, priorities and
  optional night suppression.
- Temporary displays over DDP with restore of the previous plugin and schedule:
  `show_icon` (21 icons or a number), `draw_frame`, `clear`, `show_graph` (values or
  sensor history), `restore_display`.
- `select_plugin`, `set_brightness_schedule`, `set_plugin_schedule`.
- Diagnostics, repair issues for long outages and too-old firmware.

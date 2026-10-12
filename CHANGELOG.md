# Changelog

Builds are numbered `YYYY.MM.DD.BUILD`. Everything before the first entry is the upstream
[jaysoffian/ha-lumagen](https://github.com/jaysoffian/ha-lumagen) history, preserved in this
repository's git log (up to upstream commit `4f32791`, 2026-03-27).

## v2026.10.12.1

First build of the Ltek version, forked from jaysoffian/ha-lumagen `4f32791`.

### Connection fixes

- Each TCP connection has a generation number, so a stale read loop from an old connection can no longer tear down a newer, healthy one. Previously this caused random drops minutes after a reconnect.
- Sockets are aborted (TCP RST) instead of closed gracefully, so single-client adapters (Global Cache iTach default mode) free their slot immediately. TCP keepalive is enabled.
- A failed setup (no response, label query timeout, unexpected error) now disconnects before HA retries. Previously the orphaned client and its reconnect loop competed with every retry for the adapter.
- **Connected** now means the Lumagen answered `ZQS00`, not just that TCP opened. Reconnect backoff (1 → 60 s) resets only after a verified connection.
- Liveness counts every received byte, including command echo.
- New send watchdog: no reply within 2 s of a command → reconnect. Modes: Auto / Echo / Query / Off.
- Commands sent while disconnected, or remote commands in standby, now raise an error in HA instead of being dropped silently.

### New

- **Connected** binary sensor with health attributes. Diagnostic sensors: Last Data Received, Reconnects, Last Disconnect Reason. Diagnostics download with the last 50 rx/tx lines.
- **Volume display:** follows a volume (number / input_number / sensor / media_player) and mute entity and draws it on the OSD using a pattern builder (lines, bar type incl. center-out, placement, width, fill / empty / end-cap characters, label, value format, mute display), with a preview in the options flow. New `lumagen.show_osd_volume` action takes the same options.
- **OSD colors** option (applied after power-on) and `lumagen.set_osd_colors` action (`ZY418`).
- **CMS** and **Style** selects (`ZY530`; the CMS select targets SDR or HDR based on the current source).
- **Reset Auto Aspect** button (`ZY550`), **Hotplug All Inputs** button and `lumagen.hotplug` action (`ZY520`).
- **Game Mode** binary sensor (`ZQI53`) and **HDR Max/Min Mastering Luminance** / **HDR MaxCLL** sensors (`ZQI52`), queried automatically on input/signal change.
- Remote `send_command` honors `num_repeats` and `delay_secs`.
- Aspect ratio **1.66** (`+w`) added to the Aspect Ratio select.
- All new entities are disabled by default except Connected. The volume display is off until configured.

### Changed

- Options are now a menu: Aspect ratio menu, Volume display, OSD colors, Connection.
- After any message uses a block character (`ZB`), later messages re-point `ZB` at a character not in their text, so letters like `X` don't turn into solid blocks. The volume bar picks a block character that isn't in its label.
- Uses `entry.runtime_data` instead of `hass.data`.
- Docs: removed the nonexistent "Show input aspect" button, corrected OSD max duration (8), documented iTach setup, updated `docs/architecture.md`.

# Architecture

The integration has no external dependencies. Communication with the Lumagen is handled by `client.py`, a self-contained async TCP client.

## Event-Driven Updates

The coordinator sets `update_interval=None` — no polling. All state updates come from the TCP stream:

- **Mode changes**: the Lumagen pushes `!I25,…` unsolicited (Full v5)
- **Power changes**: `Power-up complete.` / `POWER OFF.` sentinels
- **Input/memory changes**: included in ZQI25 response
- **Keepalive**: `ZQI25` sent after 30 s of idle; any received data resets
  the timer

Device state is split into config (stored on disk) and signal (unsolicited). The following **State Management** section details the startup sequence, optimistic vs authoritative state, NLS caveats, and connection lifecycle.

For the full RS-232 command and query reference, see the [RS-232 Command Reference](./rs232_command_reference.md).

## State Management

The HA integration categorizes Lumagen device state into two tiers based
on how often each piece of data changes, which determines when and how it
is fetched.

### 1. Config state (stored on disk, fetched on demand)

Data that is configured once on the Lumagen and rarely changes. Persisted
to HA storage (`lumagen.<entry_id>.info`) so it survives HA restarts
without querying the device.

| Data             | Command | Notes                                      |
|------------------|---------|----------------------------------------------|
| Model / serial   | ZQS01   | Only changes on hardware swap                |
| Firmware version | ZQS01   | Changes after firmware update                 |
| Input labels     | ZQS1*   | 40 labels (A0-D9), set via Lumagen menus      |
| Mode/CMS/Style labels | ZQS1* | 24 labels (custom mode, CMS, style)       |

Model, serial, firmware, and labels are shown in the UI but not exposed
as separate entities — identity fields live in HA's device info, and
labels populate the Input select dropdown.

#### What we deliberately don't expose as HA entities

The Lumagen has many settings that are configured once per input (or
globally) via the Lumagen menu and then left alone. These are poor
candidates for HA entities because:

1. **No query command** — the device provides no way to read the current
   value, so the entity can't show the real state after an HA restart or
   a Lumagen reboot.
2. **No automation value** — these are "set and forget" settings with no
   realistic scenario where you'd want HA to change them dynamically.
3. **Saved on the device** — switching inputs already applies the right
   per-input configuration automatically.

| Setting         | Command  | Why excluded                                        |
|-----------------|----------|-----------------------------------------------------|
| Game mode (set) | ZY551    | Per-input, saved on device. Its state is shown read-only via `ZQI53` (Game Mode binary sensor). |
| Min fan speed   | ZY552    | Global hardware setting. No query command — state lost on restart. |
| Subtitle shift  | ZY553    | Per-input, no query command, no automation use case. |

The TUI commands for min fan speed and subtitle shift remain available
for interactive testing and debugging.

**When fetched:** On first setup via `query_config()` (ZQS01 + all
labels), then cached across restarts. The "Reload config" button
re-fetches from the device.

### 2. Signal state (unsolicited + keepalive)

Volatile state that changes as the source signal changes or the user
switches inputs/memory. The Lumagen reports most of this automatically
when configured with "Report mode changes: Full v5" (unsolicited ZQI25).

| Data                        | Source       |
|-----------------------------|--------------|
| Power on/off                | Unsolicited sentinels (`Power-up complete.` / `POWER OFF.`), ZQI25 v5 field PWR |
| Input selection             | ZQI25 unsolicited (v3+ fields II/KK) |
| Input memory (A/B/C/D)      | ZQI25 unsolicited (v5 field MEM) |
| Input configuration         | ZQI25 unsolicited |
| Input video status          | ZQI25 unsolicited (field 0: No Source/Active Video/Test Pattern) |
| Source resolution/rate      | ZQI25 unsolicited |
| Source aspect (raster/content/detected) | ZQI25 unsolicited |
| Source dynamic range (SDR/HDR) | ZQI25 unsolicited |
| Source mode (progressive/interlaced) | ZQI25 unsolicited |
| Source 3D mode              | ZQI25 unsolicited (field 3) |
| NLS status                  | ZQI25 unsolicited (field 7: `N` = active, `-` = off) |
| Output resolution/rate/aspect | ZQI25 unsolicited |
| Output mode (progressive/interlaced) | ZQI25 unsolicited (v2+ field 18) |
| Output colorspace           | ZQI25 unsolicited |
| Output 3D mode              | ZQI25 unsolicited (field 8) |
| Active outputs (bitmask)    | ZQI25 unsolicited (field 9, WWWW hex) |
| Output CMS                  | ZQI25 unsolicited |
| Output Style                | ZQI25 unsolicited |

**Connection open:** Power is reset to None on every TCP connect
(including reconnects) so that `query_runtime()` always starts with
ZQS02 to discover actual power state.

**Keepalive:** When the connection has been idle for 30 seconds (no data
received at all — configurable), a probe is sent via `query_runtime()`:
- **Device on:** ZQI25+ZQI54 — full signal state + auto aspect
- **Device off/unknown:** ZQS02 — power status check

Any received data — including unsolicited ZQI25 reports — resets the idle
timer. This means during active use (source changes, input switches), no
keepalive traffic is generated; the device's own reports prove liveness.

### 3. Optimistic vs authoritative state

Some controls set optimistic state for instant UI feedback, then let the
next device response confirm or correct it.

**Optimistic (single-command, reliable):**
- Power on/off, input selection, input memory, auto aspect toggle
- Aspect ratio selection (non-NLS): set immediately, confirmed by I54 + I25 queries

**Authoritative only (multi-command or unreliable):**
- NLS button: sends `N`, then queries I25 for the final state. No
  optimistic state is set.
- Reset auto aspect button (ZY550): queries I54 + I25 afterward to get the
  device's actual state.
- CMS / Style selects (ZY530): query I25 afterward. The CMS select sets the
  SDR CMS while the source is SDR and the HDR CMS while it is HDR.

#### NLS caveats

NLS (Non-Linear Stretch) on the Lumagen remote is a two-button sequence:
press an aspect ratio (1.33, 1.78, or 1.85) then press NLS. In the
integration, pick the aspect ratio in the Aspect Ratio select, then press the
NLS button.

Known device-level issues:
- **1.85 NLS is unreliable**: works roughly 50% of the time with a 1.78
  source. The device sets the aspect to 1.85 but sometimes does not
  engage NLS. This is a firmware limitation, not an integration bug.
- **1.33 NLS and 1.78 NLS are reliable** in testing.
- Selecting any aspect ratio disables auto aspect. Selecting "Auto" re-enables it.
- "Reset auto aspect" clears NLS and re-enables auto aspect detection.

#### Aspect / auto aspect interaction

| Action              | Auto aspect | NLS    | Aspect              |
|---------------------|-------------|--------|---------------------|
| Select "Auto"       | On          | Off    | (device-detected)   |
| Select a ratio      | Off         | Off    | Set to selection    |
| Press NLS           | —           | On*    | —                   |
| Reset auto aspect   | On          | Off    | (device-detected)   |
| Toggle auto aspect  | Toggled     | —      | —                   |

*NLS engagement depends on device firmware; 1.85 NLS is unreliable.

### Startup sequence

1. Connect to the adapter and verify the Lumagen answers `ZQS00`
   (3 s). A failure disconnects and raises `ConfigEntryNotReady` (HA
   retries). Any failure later in setup also disconnects first, so no
   orphaned socket holds a single-client adapter's slot.
2. Load config state from HA storage (identity, labels) to seed device
   info before device responds.
3. If no stored config exists (first setup), `query_config()` sends
   ZQS01 (identity), waits for the response, then queries all 64
   labels sequentially. If identity times out or any label fails →
   `ConfigEntryNotReady` (HA retries). When stored config exists
   (normal restarts), this step is skipped entirely.
4. `query_runtime()` fires (non-blocking). Power is unknown at this
   point so it sends ZQS02. Entities start unavailable until the
   power response arrives.

On power-on (off → on transition detected from ZQS02 poll response or
`Power-up complete.` sentinel):

1. Wait 10 seconds for the device to finish initialization.
2. `query_runtime()` sends ZQI25+ZQI54 to get full signal state.

Note: `None` to `on` transitions (initial state discovery after HA
restart or reconnect) do NOT trigger the power-on handler — the startup
sequence already handles this case.

### Connection lifecycle

- **Verified connect:** `connected` becomes True only after the Lumagen
  answers `ZQS00` through the adapter. An adapter that accepts TCP but
  passes no data (wedged, wrong serial settings, IP conflict) is reported as
  disconnected. The same check tells us whether Echo-RS232 is on.
- **Generations:** every TCP connection gets a generation number and its
  own reader. A read loop can only tear down its own generation, so a stale
  socket from an earlier connection never kills a newer one.
- **Hard teardown:** sockets are aborted (TCP RST), not closed gracefully,
  so single-client adapters (iTach in its default mode) free the slot
  immediately. TCP keepalive is enabled on the socket as well.
- **Liveness:** every received byte, including command echo (which has no
  line terminator), updates the idle timer.
- **Send watchdog** (option; default Auto): after a command, at least one
  byte must arrive within 2 s or the link is considered dead.
  - *Echo*: relies on the Lumagen echoing the command.
  - *Query*: appends `ZQS00` to each command (works with Echo off).
  - *Auto*: echo if detected at connect, otherwise query.
  - *Off*: keepalive only.
  Power on/off commands suspend the watchdog for 30 s while the device
  boots or shuts down.
- **Keepalive:** after 30 s (configurable) of silence, `query_runtime()` is
  sent; no reply within 5 s → reconnect.
- **Reconnect:** exponential backoff 1 s → 60 s. Backoff resets only after a
  *verified* connection, so a wedged adapter doesn't cause a tight loop.
  Power state is NOT reset to None on disconnect, avoiding spurious
  power-on detection.
- **Errors:** commands sent while disconnected raise
  `LumagenConnectionError`, surfaced in HA as an error on the action.
- **Health:** `LinkHealth` (disconnects, reconnects, consecutive failures,
  last reason, echo detected, watchdog mode, last data time) feeds the
  Connected binary sensor, diagnostic sensors and diagnostics download. The
  last 50 sent/received lines are kept for diagnostics.

### Follow-up queries

When an I21–I25 report shows a new input, memory, resolution, rate, or
dynamic range, the client queries game mode (`ZQI53`) and, for HDR
sources, HDR metadata (`ZQI52`) 0.5 s later. HDR metadata is cleared when
the source is SDR.

### Volume OSD

`volume_osd.py` follows a volume entity (number / input_number / sensor /
media_player) and an optional mute entity, rendering with the pattern
builder in `osd_pattern.py` (pure functions, fully unit-tested). It ignores
transitions from/to unavailable/unknown, always clears a persistent mute on
unmute, coalesces rapid changes, skips repeats, and only sends while the
Lumagen is connected and on.

`ZB` (block character) may persist on the device, so once a message has
used it, later messages re-point it at a character not in their text.

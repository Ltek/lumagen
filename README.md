# Lumagen Radiance Pro Integration for Home Assistant

This [integration](https://www.home-assistant.io/getting-started/concepts-terminology/#integrations) connects your [Lumagen Radiance Pro](https://www.lumagen.com/products-sales/p/explore-radiance-pro) video processor to your [Home Assistant](https://www.home-assistant.io) installation.

> **Credit:** This integration is built on [**ha-lumagen** by Jay Soffian (@jaysoffian)](https://github.com/jaysoffian/ha-lumagen). Jay designed and wrote the original integration: the async RS-232 client, the event-driven state model, label handling, aspect-ratio and NLS logic, the OSD services, the TUI, and the RS-232 command reference in [`docs/`](docs/). This version adds connection hardening and new features on top of his work. The full upstream commit history is preserved in this repository, and it is distributed under the same [MIT license](LICENSE). If you only need the original feature set, please use and support [his repository](https://github.com/jaysoffian/ha-lumagen).

Current build: **v2026.10.12.1** · full history in [CHANGELOG.md](CHANGELOG.md)

### What this version adds

- **Connection hardening** (especially for the Global Cache iTach IP2SL):
  - Reports *Connected* only when the Lumagen itself answers, not just the TCP adapter.
  - Detects a dead link within about 2 s of a command.
  - Frees the adapter's connection slot immediately on disconnect.
  - Old connections can never tear down a new one.
  - Failed setups no longer leave a socket open.
- **Connected** binary sensor, plus optional link-health sensors and a diagnostics download.
- **Volume display:** follows your AVR / processor volume and mute and draws it on the Lumagen OSD with a configurable pattern. No automation needed.
- **New controls:**
  - CMS and Style selects.
  - Reset Auto Aspect and HDMI Hotplug buttons.
  - Game Mode and HDR metadata (mastering luminance, MaxCLL) sensors.
  - OSD colors.
  - Remote `num_repeats` / `delay_secs`.
- **Everything new is opt-in.** New entities start disabled, the volume display is off until configured, and the link watchdog can be turned off. A fresh install looks like the original plus one *Connected* sensor.

## TCP/IP to Serial Adapter Setup

Required: A TCP/IP to Serial adapter such as the [Global Cache iTach IP2SL](https://www.amazon.com/Global-Cache-iTach-Serial-IP2SL/dp/B0051BU1X4) or [USR-TCP232-302](https://www.amazon.com/USR-TCP232-302-Serial-Ethernet-Converter-Support/dp/B01GPGPEBM)\* connected to the Lumagen's RS-232 port.

Connect the adapter to the Lumagen's RS-232 DB-9 male DTE port using the appropriate cable:

- The IP2SL has a DB-9 male DTE port. Connect it using a [DB-9 female-to-female null-modem cable](https://www.startech.com/en-us/cables/scnm9ff1mbk).
- The USR-TCP232-302 has a DB-9 female DCE port. Connect it using a [DB-9 male-to-female straight-through cable](https://www.startech.com/en-us/cables/mxt1001mbk).

The adapter's serial port settings must match the Lumagen's RS-232 port settings (default: 9600 bps, 8N1, no flow control).

Connect the adapter to your local network. You'll need the adapter's IP address and port (default 4999) when configuring the integration later.

\* *The original integration is developed and tested against the USR-TCP232-302. This version is also used with the Global Cache iTach IP2SL.*

### Global Cache iTach IP2SL notes

- Give the iTach a **DHCP reservation**, or a static IP *outside* your router's DHCP pool. An IP conflict with another device causes exactly the "shows connected but nothing works" symptom.
- By default the iTach serial port accepts **one** TCP client. This integration releases the slot immediately on disconnect. If you also want another controller or the TUI connected at the same time, enable **Serial Multiconnection Mode** on the iTach's *Serial* web page.
- Use a null-modem cable (see above) and 9600 8N1, no flow control.

## Lumagen Setup

The Lumagen should be configured as follows for the integration to work correctly.

1. **MENU → Other → I/O Setup → RS-232 Setup:**
   - **Echo-RS232**: On (Lumagen recommends "On". If set to "Off" it may affect the ability to do software updates. *This integration should work either way, but is tested with it On.*)
   - **Echo-USB**: On (Lumagen recommends "On". If set to "Off" it may affect the ability to do software updates. *Mentioned only for completeness as the TCP/IP to serial adapter connects to the RS-232 port.*)
   - **Delimiters**: Off (Lumagen recommends "Off". This works reliably and is easier to implement. *This integration WILL NOT work unless Delimiters=Off.*)
   - **Report mode changes**: Full v5 (Optional but recommended. *Enables the integration to receive real-time updates from the Lumagen.*)
2. **MENU → Other → OnOff Setup:**
    - **On Message**: N (Message may interfere with integration.)
    - **Off Message**: N (Message may interfere with integration.)
3. **MENU → Input → Options → Aspect Setup → Options:**
   - **Input Aspects used**: Extended (Optional. Adds 1.37, 1.66, 2.10, 2.55, and 2.76 to supported aspects. Also see [Configuring the Aspect Ratio Menu](#configuring-the-aspect-ratio-menu) below.)
4. **MENU → Input → Options → Aspect Setup → Auto Aspect:**
   - **Sticky aspect override**: On (Optional. Manually selected aspect ratio will "stick" until AA is re-enabled.)

## Installation

### HACS

1. Install [HACS](https://hacs.xyz), then either:
   1. [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Ltek&repository=lumagen&category=integration)

   Or:

   1. Open HACS → Integrations
   2. Open triple-dot menu ( ⠇) → Custom repositories
   3. Add this repository's URL (`https://github.com/Ltek/lumagen`), category "Integration"
2. Install this integration and restart Home Assistant

**Switching from jaysoffian/ha-lumagen:** both use the `lumagen` domain, so your config entry and entity IDs carry over. Remove the old repository in HACS, add this one, install, and restart. Only one of the two can be installed at a time.

### Manual

Copy `custom_components/lumagen` into your Home Assistant `custom_components` directory and restart.

## Configuration

1. Settings → Devices & Services → Add Integration → Lumagen
2. Enter the hostname (or IP address) and port (default: 4999) of your TCP/IP to Serial Adapter.

The integration tests the connection before completing setup. Configuration information that rarely changes (identity, firmware revision, and labels) is loaded from your Lumagen on first setup and cached across HA restarts. Use the **Reload config** button to refresh this information in the future.

After setup, **Settings → Devices & Services → Lumagen → Configure** opens a menu:

| Option | What it does |
|---|---|
| **Aspect ratio menu** | Choose which ratios appear in the Aspect Ratio select. |
| **Volume display (OSD)** | Follow a volume / mute entity and show it on screen. See [Volume display](#volume-display). |
| **OSD colors** | Text and background color and opacity for OSD messages, applied after each power-on. |
| **Connection / link watchdog** | How fast a dead link is detected. See [Connection and link watchdog](#connection-and-link-watchdog). |

Entities marked *(disabled by default)* below are created but off. Enable them on the device page (**Settings → Devices & Services → Lumagen → device → entities**).

## Entities

### Switches

- **Power** — Turn device on / standby.
- **Auto Aspect** — Enable / disable auto aspect detection.

### Buttons

- **NLS** - Enable/disable [non-linear stretch](#non-linear-stretch).
- **Reset Auto Aspect** *(disabled by default)* — Reset and restart automatic aspect detection (ZY550).
- **Hotplug All Inputs** *(disabled by default)* — Toggle HDMI hotplug so sources re-read the EDID. Fixes "no picture / wrong format / no audio" without power-cycling the source. For a single input, use the `lumagen.hotplug` action.
- **Restart outputs** — Restart outputs if your TV/projector has trouble locking on the signal.
- **Reload config** — Reload configuration (identity, firmware revision, and labels) from your Lumagen. This queries all 64 labels sequentially and may take a minute or two to complete. There is no progress indication — verify by checking that labels or firmware version updated.

### Selects

- **Input** — Select input.
- **Aspect Ratio** — Auto, Letterbox, 1.33, 1.37, 1.66, 1.78, 1.85, 1.90, 2.00, 2.10, 2.20, 2.35, 2.40, 2.55, 2.76. [Configurable](#configuring-the-aspect-ratio-menu).
- **Memory** — Select input memory A / B / C / D.
- **CMS** *(disabled by default)* — Select the output CMS (0–7, shown with your labels). While the source is SDR this sets the SDR CMS; while it is HDR it sets the HDR/Rec.2020 CMS (`ZY530`).
- **Style** *(disabled by default)* — Select the output style (0–7, shown with your labels).

Changes made with CMS / Style are not saved to the Lumagen's flash until you save the configuration on the device.

### Binary sensors

- **Connected** (diagnostic) — On only while the Lumagen answers through the adapter. Attributes show disconnects, reconnects, consecutive failures, the last disconnect reason, whether echo was detected, and the active watchdog mode. Always available, so you can alert on it.
- **Game Mode** *(disabled by default)* — Game mode of the current input (`ZQI53`, read-only).

### Sensors

All sensors require the device to be active (not in standby).

- **Logical Input** — Current logical input number
- **Physical Input** — Current physical input
- **Input Configuration** — Active input config number
- **Input Video Status** — No Source / Active Video / Test Pattern
- **Source Resolution** — Source vertical resolution
- **Source Refresh Rate** — Source vertical refresh rate
- **Source Content Aspect Ratio** — Detected source content aspect
- **Source Raster Aspect Ratio** — Source raster aspect
- **Source Dynamic Range** — SDR / HDR
- **Source Mode** — Progressive / Interlaced
- **Source 3D Mode** — Off / Frame Sequential / Frame Packed / Top-Bottom / Side-by-Side
- **NLS** — Non-linear stretch active
- **Detected Content Aspect Ratio** — Auto-detected content aspect
- **Detected Raster Aspect Ratio** — Auto-detected raster aspect
- **Output Resolution** — Output vertical resolution
- **Output Refresh Rate** — Output vertical refresh rate
- **Output Aspect Ratio** — Output aspect ratio
- **Output Mode** — Progressive / Interlaced
- **Output Colorspace** — Output colorspace (e.g. BT.709, BT.2020)
- **Output 3D Mode** — Off / Frame Sequential / Frame Packed / Top-Bottom / Side-by-Side
- **Active Outputs** — Which outputs (1-4) are active (comma-separated list)
- **Output CMS** — Active color management system (0–7)
- **Output CMS Label** — Label for the active CMS
- **Output Style** — Active output style (0–7)
- **Output Style Label** — Label for the active output style
- **Input Label** — Label for the current input
- **HDR Max Mastering Luminance**, **HDR Min Mastering Luminance**, **HDR MaxCLL** *(disabled by default)* — From `ZQI52`, in nits. Queried automatically when the input or signal changes. Unknown while the source is SDR.

Diagnostic sensors *(disabled by default; available even while disconnected)*:

- **Last Data Received** — Timestamp of the last byte received from the Lumagen.
- **Reconnects** — Number of successful reconnects.
- **Last Disconnect Reason** — e.g. `keepalive timeout`, `no response within 2s of a command`, `no response from Lumagen (ZQS00)`.

Device identity (model, serial, firmware) is shown in HA's device info rather than as separate entities.

### Remote

Send navigation and control commands to the Lumagen menu system. Available commands match the [physical (extended) remote](https://github.com/user-attachments/assets/7d1968e4-d3e1-43d7-8ebb-ef41a5e7e2dc):

- `on`, `0`..`9`, `10+`, `stby`
- `clear`, `help`, `exit`, `menu`
- `up`, `down`, `left`, `right`, `ok`
- `hdr_setup`
- `input`, `zone`, `alt`, `prev`
- `4:3`, `16:9`, `1.85`, `2.00`, `2.20`, `2.40`
- `lbox`, `1.90`, `2.35`, `nls`
- `a`, `b`, `c`, `d`
- `auto_aspect_disable`, `auto_aspect_enable`, `pattern`, `save`

## Aspect Ratio and Auto Aspect

The Aspect Ratio select and Auto Aspect switch are kept in sync:

| Action              | Auto Aspect | Aspect              |
|---------------------|-------------|---------------------|
| Select "Auto"       | On          | (device-detected)   |
| Select a ratio      | Off         | Set to selection    |

### Configuring the Aspect Ratio Menu

By default all supported aspect ratios appear in the select menu. To show only the ratios you use, go to **Settings → Devices & Services → Lumagen → Configure** and select which ratios to include.

### Non-Linear Stretch

NLS stretches a narrower aspect to fill a wider display non-linearly (more stretch at the edges, less in the center). NLS is exposed as a non-stateful button entity (as opposed to a stateful switch) because the Lumagen's NLS behavior is not consistent across aspect ratios: it retains NLS state on the 1.85 AR, but no others. i.e. when NLS is activated on 1.85, if you switch to another AR, NLS is de-activated. When you switch back to 1.85, it's re-activated. All other ARs "forget" their NLS state.

## Usage Examples

### Power

```yaml
action: switch.turn_on
target:
  entity_id: switch.lumagen_radiancepro_power
```

### Input Selection

```yaml
action: select.select_option
target:
  entity_id: select.lumagen_radiancepro_input
data:
  option: "HDMI 1"
```

### Aspect Ratio

```yaml
action: select.select_option
target:
  entity_id: select.lumagen_radiancepro_aspect_ratio
data:
  option: "2.35"
```

### Remote Commands

```yaml
action: remote.send_command
target:
  entity_id: remote.lumagen_radiancepro
data:
  command:
    - menu
    - down
    - ok
```

`num_repeats` and `delay_secs` are supported. For example, press Down five times, 0.3 s apart:

```yaml
action: remote.send_command
target:
  entity_id: remote.lumagen_radiancepro
data:
  command: down
  num_repeats: 5
  delay_secs: 0.3
```

### On-Screen Display

The Lumagen Radiance Pro has an On-Screen Display that can show up to two lines of 30 characters each.

This integration provides the following [services](./custom_components/lumagen/services.yaml) to control the OSD:

- `lumagen.show_osd_message`: Show an OSD message
- `lumagen.show_osd_volume`: Show a volume value or mute using the [pattern builder](#volume-display)
- `lumagen.show_osd_volume_bar`: Show a volume bar (original fixed layout)
- `lumagen.clear_osd_message`: Clear any OSD message
- `lumagen.set_osd_colors`: Set OSD text/background color and opacity
- `lumagen.hotplug`: Toggle HDMI hotplug on one input or all inputs

Example:

```yaml
action: lumagen.show_osd_message
data:
  entity_id: remote.lumagen_radiancepro  # any entity from the Lumagen device
  line_one: "Hello" # Maximum 30 characters (ASCII 0x20 - 0x7a)
  line_two: "World" # Optional second line
  duration: 5 # Clear in 5 secs. Max is 8. Default is 3. Use 0 to disable clearing.
  block_char: "X" # Optional character to render as █ if it appears in message.

# See volume bar examples below
```

## Volume display

The integration can follow your AVR or processor's volume and mute entities and draw them on the Lumagen OSD itself. You don't need an automation. Go to **Configure → Volume display (OSD)**, pick the entities, design the pattern, then **Submit**. You'll get a preview at min / 42% / max / muted before saving.

**Sources**

- **Volume entity:** a `number` / `input_number` / `sensor` (uses its state and `min`/`max`, e.g. `number.isp_volume_level`) or a `media_player` (uses `volume_level`).
- **Mute entity (optional):** a `switch` / `input_boolean` / `binary_sensor` (e.g. `switch.isp_mute`). Leave empty to use the media player's own mute.
- **Full-scale value (optional):** the value that draws a full bar, e.g. `80` if you cap volume at 80.

**Built-in behavior**

- Nothing pops up when the AVR/processor powers on or HA restarts. Changes from or to `unavailable` / `unknown` are ignored.
- A persistent mute message is always cleared on unmute, including when the processor turns off while muted.
- Rapid volume steps collapse to the latest value, and repeats of the same value are skipped.
- Nothing is sent while the Lumagen is in standby or disconnected.

**Pattern builder**

| Option | Choices |
|---|---|
| Lines | 1 line, or 2 lines (label/value above, full-width bar below) |
| Bar type | None (text only), Left to right, Center out (bar grows outward from the value on both sides) |
| Value placement | Left, Center, Right |
| Bar width | 0 = fill remaining space, or a fixed number of cells |
| Bar fill character | Solid block, or any single character (`=`, `#`, `*`, `+`, `>`, …) |
| Empty placeholder | None (blank) or any single character (`-`, `.`, `:`, `_`, …) |
| End caps | None, `[ ]`, `< >`, `( )`, or any two characters |
| Label / text after value | Free text, e.g. `Volume`, `Sound`, `- Volume` / `%`, ` dB`, ` -` |
| Value shown as | Raw value, percent of range, or custom `value × scale + offset` |
| Decimals, Min/Max text | 0–2 decimals; optionally show `Min` / `Max` at the ends |
| When muted | Mute text (default `- MUTE -`), empty bar with label, or nothing; keep on screen until unmuted or time out |
| Display time | 1–8 s |

The Lumagen OSD shows 2 lines × 30 characters, using characters from space to lowercase `z`. That excludes `|`, `~`, `{` and `}`. The bar keeps the same position as the number of digits changes.

**Examples** (`█` = solid)

```text
Left to right, value left:     Volume 42  [███████----------]
Value right, no caps/empty:    █████████               Vol 42
Center out:                    -------█████ 42 █████--------
Text only:                     - Volume 42 -        /  - MUTE -
Two lines:                     Volume -58 dB
                               █████████████.................
```

For a Denon/Marantz media player in dB, use *Value shown as: Custom*, scale `100`, offset `-80`, decimals `1`, text after value ` dB`.

### Volume display from an automation

`lumagen.show_osd_volume` takes the same pattern options. Any option you leave out comes from the configured volume display (or the defaults), so this is enough:

```yaml
action: lumagen.show_osd_volume
data:
  entity_id: remote.lumagen_radiancepro
  value: "{{ states('number.isp_volume_level') }}"
  minimum: 0
  maximum: 100
  muted: "{{ is_state('switch.isp_mute', 'on') }}"
```

## Connection and link watchdog

**Configure → Connection / link watchdog**

| Setting | Default | Meaning |
|---|---|---|
| Link watchdog | Auto | After each command, expect a reply within the timeout or reconnect. **Auto** uses the Lumagen's command echo if Echo-RS232 is On, otherwise **Query** (appends a `ZQS00` query to each command). **Off** = keepalive only. |
| Watchdog timeout | 2 s | |
| Keepalive interval | 30 s | Probe the link after this long without any data. |

Power on/off commands pause the watchdog for 30 s while the Lumagen boots or shuts down.

To get notified if the link stays down:

```yaml
alias: "Lumagen link down"
triggers:
  - trigger: state
    entity_id: binary_sensor.lumagen_radiancepro_connected
    to: "off"
    for: "00:05:00"
actions:
  - action: notify.notify
    data:
      message: >-
        Lumagen serial link down:
        {{ state_attr('binary_sensor.lumagen_radiancepro_connected', 'last_disconnect_reason') }}
```

If your adapter is on a smart plug or PoE port, the same trigger can power-cycle it.

### Automation Examples

**Settings → Automations & scenes → +Create automation → Create new automation → triple-dot menu (⠇) → Edit in YAML**

#### Switch input on playback

```yaml
alias: "Switch to Apple TV"
trigger:
  - platform: state
    entity_id: media_player.apple_tv
    to: "playing"
action:
  - action: select.select_option
    target:
      entity_id: select.lumagen_radiancepro_input
    data:
      option: "HDMI 2"
```

### Control the On-Screen Display

##### AVR Volume

Show volume changes from the [Denon AVR integration](https://www.home-assistant.io/integrations/denonavr/) on the Lumagen's OSD: `63.5% ███████████████         `

The volume change is displayed for 1 second.

```yaml
alias: "Show AVR volume on Lumagen"
triggers:
  - trigger: state
    entity_id: media_player.denon_avr_x3800h  # adjust to your entity
    attribute: volume_level
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.volume_level is defined }}"
actions:
  - action: lumagen.show_osd_volume_bar
    data:
      entity_id: remote.lumagen_radiancepro
      level: "{{ trigger.to_state.attributes.volume_level }}"
mode: single
```

##### AVR Volume (scaled)

Scale the bar so that volume level 0.8 is a full bar: `80.0% ████████████████████████`

You might want to do this if you set a volume limit on your AVR.

```yaml
alias: "Show AVR volume on Lumagen (scaled)"
triggers:
  - trigger: state
    entity_id: media_player.denon_avr_x3800h  # adjust to your entity
    attribute: volume_level
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.volume_level is defined }}"
actions:
  - action: lumagen.show_osd_volume_bar
    data:
      entity_id: remote.lumagen_radiancepro
      level: "{{ trigger.to_state.attributes.volume_level / 0.8 }}"
      label: >-
        {% if trigger.to_state.attributes.volume_level == 0 %}
          Min
        {% elif trigger.to_state.attributes.volume_level >= 0.8 %}
          Max
        {% else %}
          {{ (trigger.to_state.attributes.volume_level * 100) | round(1) }}
        {% endif %}
mode: single
```

##### AVR Volume (decibels)

Show the volume level in decibels instead of a percentage: `-16.5 ███████████████         `

Denon / Marantz AVRs can display their volume in decibels (-79.5 dB — +18.0 dB) as an alternative to the 0–98 scale. This is how you'd mimic the decibel display.

```yaml
alias: "Show AVR volume on Lumagen (dB)"
triggers:
  - trigger: state
    entity_id: media_player.denon_avr_x3800h  # adjust to your entity
    attribute: volume_level
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.volume_level is defined }}"
actions:
  - action: lumagen.show_osd_volume_bar
    data:
      entity_id: remote.lumagen_radiancepro
      level: "{{ trigger.to_state.attributes.volume_level }}"
      label: >-
        {% if trigger.to_state.attributes.volume_level == 0 %}
          Min
        {% elif trigger.to_state.attributes.volume_level == 1 %}
          Max
        {% else %}
          {{ (trigger.to_state.attributes.volume_level * 100 - 80) | round(1) }}
        {% endif %}
mode: single
```

##### AVR Mute Status

Show "Mute" on screen as long as the AVR is muted.

```yaml
alias: "Show mute on Lumagen"
triggers:
  - trigger: state
    entity_id: media_player.denon_avr_x3800h  # adjust to your entity
    attribute: is_volume_muted
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.is_volume_muted is defined }}"
actions:
  - if: "{{ trigger.to_state.attributes.is_volume_muted }}"
    then:
      - action: lumagen.show_osd_message
        data:
          entity_id: remote.lumagen_radiancepro
          line_one: "Mute"
          duration: 0
    else:
      - action: lumagen.clear_osd_message
        data:
          entity_id: remote.lumagen_radiancepro
mode: single
```

## Troubleshooting

### Connection fails during setup

- Verify the TCP/IP-to-serial adapter is reachable at the configured IP/port, and that no other device is using the same IP
- Confirm the adapter's serial settings match the Lumagen's (9600 8N1)
- Try with the Lumagen powered on. It may not respond if its standby power is configured to "Lowest".

### Entities show unavailable

- Sensors require the device to be active (not in standby)
- Power switch and Reload Config are available whenever connected
- Check the **Connected** binary sensor and its attributes. `last_disconnect_reason` says why the link dropped.
- Check Home Assistant logs for keepalive timeouts or reconnect messages
- **Settings → Devices & Services → Lumagen → ⋮ → Download diagnostics** includes connection health and the last 50 lines sent and received.

### Shows connected but commands do nothing

This version treats that as disconnected: *Connected* goes off within about 2 s of the next command (or about 35 s when idle) and reconnects automatically. If it keeps happening:

- Look for an IP conflict on the adapter's address.
- With an iTach, make sure nothing else holds its single serial connection (or enable Serial Multiconnection Mode).
- If you set Echo-RS232 = Off on the Lumagen, leave the watchdog on **Auto** or **Query**.

### Input source dropdown shows "Input 1", "Input 2", …

1. Confirm you have custom labels configured on your Lumagen
2. Press the **Reload config** button entity to fetch labels from your Lumagen
3. Labels are per input memory — switching memories shows that memory's labels

### TUI

This repo includes a TUI (requires [uv](https://docs.astral.sh/uv/getting-started/installation/)) for exercising the client against a real Lumagen:

```bash
./tui.py <host> [port]
# or via env vars:
LUMAGEN_HOST=lrp LUMAGEN_PORT=5555 ./tui.py
```

<img src="assets/tui.svg" alt="TUI screenshot" width="600">

## Credits

- **[Jay Soffian](https://github.com/jaysoffian)** — author of the original [ha-lumagen](https://github.com/jaysoffian/ha-lumagen) integration this is built on: the client, protocol research and documentation, entities, OSD services and TUI. Thank you, Jay.
- **LTek** — connection hardening, volume display / pattern builder, and the additional entities and services listed in [CHANGELOG.md](CHANGELOG.md).
- [Lumagen](https://www.lumagen.com) for publishing the [RS-232 command interface](https://www.lumagen.com/s/Tip0011_RS232CommandInterface_111023.pdf).

Licensed under the [MIT License](LICENSE) (original copyright Jay Soffian; modifications copyright LTek).

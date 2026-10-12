"""Constants for the Lumagen integration."""

DOMAIN = "lumagen"
DEFAULT_PORT = 4999

ERROR_CANNOT_CONNECT = "cannot_connect"

CONF_ASPECT_RATIOS = "aspect_ratios"

# Connection options
CONF_WATCHDOG = "watchdog"
CONF_WATCHDOG_TIMEOUT = "watchdog_timeout"
CONF_KEEPALIVE_INTERVAL = "keepalive_interval"
DEFAULT_WATCHDOG = "auto"
DEFAULT_WATCHDOG_TIMEOUT = 2.0
DEFAULT_KEEPALIVE_INTERVAL = 30

# Volume display options
CONF_VOLUME_ENABLED = "volume_enabled"
CONF_VOLUME_ENTITY = "volume_entity"
CONF_MUTE_ENTITY = "mute_entity"
CONF_VOLUME_FULL_SCALE = "volume_full_scale"
CONF_VOLUME_PATTERN = "volume_pattern"

# OSD color options
CONF_OSD_COLORS = "osd_colors"
CONF_OSD_FOREGROUND = "osd_foreground"
CONF_OSD_BACKGROUND = "osd_background"
CONF_OSD_BLEND = "osd_blend"
OSD_COLOR_PRESETS: dict[str, tuple[str, str, int] | None] = {
    "device": None,  # leave the Lumagen's own setting alone
    "dark_translucent": ("ffffff", "000000", 8),
    "high_contrast": ("ffff00", "000000", 15),
    "custom": None,  # use CONF_OSD_FOREGROUND / BACKGROUND / BLEND
}

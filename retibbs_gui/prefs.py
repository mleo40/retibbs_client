"""Settings and saved servers, kept as JSON in ~/.config/retibbs-gui."""

import json
import os

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "retibbs-gui")
DEFAULTS = {
    "theme": "light", "font_size": 10, "window": "", "sash": 0, "display_name": "", "alert_address": "",
    "offline_copy": False, "keep_deleted_boards": False, "last_server": "",
}


class JsonFile(dict):
    def __init__(self, name, defaults=None):
        super().__init__(defaults or {})
        self.path = os.path.join(CONFIG_DIR, name)
        try:
            with open(self.path, encoding="utf-8") as handle:
                self.update(json.load(handle))
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self, handle, indent=2)
        os.replace(temporary, self.path)


def settings():
    return JsonFile("settings.json", DEFAULTS)


def servers():
    """Saved servers: {hash: {"name": ..., "custom": bool}}. A custom name is kept when the server announces another."""
    return JsonFile("servers.json")

"""
Settings management for ComfyUI_to_webui V2
"""

import json
from pathlib import Path
from typing import Dict, Any

SETTINGS_FILE = Path(__file__).parent.parent / "plugin_settings.json"


def load_settings() -> Dict[str, Any]:
    """
    Load plugin settings from JSON file

    Returns:
        Dictionary of settings, or empty dict if file doesn't exist
    """
    if not SETTINGS_FILE.exists():
        return {}

    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            return settings if isinstance(settings, dict) else {}
    except Exception as e:
        print(f"⚠️ Failed to load settings: {e}")
        return {}


def save_settings(settings: Dict[str, Any]) -> str:
    """
    Save plugin settings to JSON file

    Args:
        settings: Dictionary of settings to save

    Returns:
        Status message
    """
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        return "✅ Settings saved successfully"
    except Exception as e:
        return f"❌ Failed to save settings: {e}"


def get_setting(key: str, default: Any = None) -> Any:
    """
    Get a single setting value

    Args:
        key: Setting key
        default: Default value if key doesn't exist

    Returns:
        Setting value or default
    """
    settings = load_settings()
    return settings.get(key, default)


def set_setting(key: str, value: Any) -> str:
    """
    Set a single setting value

    Args:
        key: Setting key
        value: Setting value

    Returns:
        Status message
    """
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)

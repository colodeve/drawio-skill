"""Style preset manager for draw.io diagrams.

This module handles loading, validating, and applying style presets.
"""

import os
import json
import platform
from typing import Dict, Any, Optional, List
from pathlib import Path

# Default palette for fallback
DEFAULT_PALETTE = {
    "primary": {"fillColor": "#dae8fc", "strokeColor": "#6c8ebf"},
    "success": {"fillColor": "#d5e8d4", "strokeColor": "#82b366"},
    "warning": {"fillColor": "#fff2cc", "strokeColor": "#d6b656"},
    "accent": {"fillColor": "#ffe6cc", "strokeColor": "#d79b00"},
    "danger": {"fillColor": "#f8cecc", "strokeColor": "#b85450"},
    "neutral": {"fillColor": "#f5f5f5", "strokeColor": "#666666"},
    "secondary": {"fillColor": "#e1d5e7", "strokeColor": "#9673a6"},
}

DEFAULT_ROLES = {
    "service": "primary",
    "database": "success",
    "queue": "warning",
    "gateway": "accent",
    "error": "danger",
    "external": "neutral",
    "security": "secondary",
}

DEFAULT_SHAPES = {
    "service": "rounded=1",
    "database": "shape=cylinder3",
    "queue": "rounded=1",
    "decision": "rhombus",
    "external": "rounded=1;dashed=1",
    "container": "swimlane;startSize=30",
}

DEFAULT_FONT = {
    "fontFamily": "Helvetica",
    "fontSize": 12,
    "titleFontSize": 14,
    "titleBold": True,
}

DEFAULT_EDGES = {
    "style": "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1",
    "arrow": "endArrow=classic;endFill=1",
    "dashedFor": [],
}


class StylePreset:
    """Represents a style preset for draw.io diagrams."""

    def __init__(self, preset_data: Dict[str, Any]):
        self.name = preset_data.get("name", "default")
        self.version = preset_data.get("version", 1)
        self.default = preset_data.get("default", False)
        self.source = preset_data.get("source", {"type": "built-in"})
        self.confidence = preset_data.get("confidence", "high")
        self.palette = preset_data.get("palette", DEFAULT_PALETTE)
        self.roles = preset_data.get("roles", DEFAULT_ROLES)
        self.shapes = preset_data.get("shapes", DEFAULT_SHAPES)
        self.font = preset_data.get("font", DEFAULT_FONT)
        self.edges = preset_data.get("edges", DEFAULT_EDGES)
        self.extras = preset_data.get("extras", {"sketch": False, "globalStrokeWidth": 1})

    def get_color_for_role(self, role: str) -> Dict[str, str]:
        """Get fillColor and strokeColor for a given role."""
        # First try the role mapping
        slot_name = self.roles.get(role)
        if slot_name and slot_name in self.palette:
            return self.palette[slot_name]

        # Fallback to canonical slot
        canonical_slots = {
            "service": "primary",
            "database": "success",
            "queue": "warning",
            "gateway": "accent",
            "error": "danger",
            "external": "neutral",
            "security": "secondary",
        }
        canonical_slot = canonical_slots.get(role)
        if canonical_slot and canonical_slot in self.palette:
            return self.palette[canonical_slot]

        # Fallback to the first available slot
        for slot in self.palette.values():
            if slot:
                return slot

        # Final fallback to default primary
        return DEFAULT_PALETTE["primary"]

    def get_shape_style(self, role: str) -> str:
        """Get the shape style prefix for a given role."""
        # Special handling for roles that reuse service shape
        if role in ["gateway", "error", "security"] and role not in self.shapes:
            return self.shapes.get("service", "rounded=1")
        return self.shapes.get(role, "rounded=1")

    def build_vertex_style(self, role: str, is_title: bool = False) -> str:
        """Build a complete vertex style string."""
        parts = []

        # Shape prefix
        parts.append(self.get_shape_style(role))

        # Colors
        colors = self.get_color_for_role(role)
        parts.append(f"fillColor={colors['fillColor']}")
        parts.append(f"strokeColor={colors['strokeColor']}")

        # Font
        if is_title and self.font.get("titleBold"):
            parts.append(f"fontFamily={self.font['fontFamily']}")
            parts.append(f"fontSize={self.font.get('titleFontSize', 14)}")
            parts.append("fontStyle=1")
        else:
            parts.append(f"fontFamily={self.font['fontFamily']}")
            parts.append(f"fontSize={self.font['fontSize']}")

        # Extras
        if self.extras.get("sketch"):
            parts.append("sketch=1")
        if self.extras.get("globalStrokeWidth") != 1:
            parts.append(f"strokeWidth={self.extras['globalStrokeWidth']}")

        # Defaults
        parts.append("whiteSpace=wrap")
        parts.append("html=1")

        return ";".join(parts)

    def build_edge_style(self, is_dashed: bool = False) -> str:
        """Build a complete edge style string."""
        parts = [self.edges["style"]]
        if self.edges.get("arrow"):
            parts.append(self.edges["arrow"])
        if is_dashed:
            parts.append("dashed=1")
        if self.extras.get("globalStrokeWidth") != 1:
            parts.append(f"strokeWidth={self.extras['globalStrokeWidth']}")
        if self.extras.get("sketch"):
            parts.append("sketch=1")
        return ";".join(parts)


class StyleManager:
    """Manages style presets for draw.io diagrams."""

    def __init__(self, skill_dir: Optional[str] = None):
        self.skill_dir = skill_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.builtin_dir = os.path.join(self.skill_dir, "styles", "built-in")
        self.user_dir = self._get_user_styles_dir()
        self._presets: Dict[str, StylePreset] = {}
        self._default_preset: Optional[StylePreset] = None

    def _get_user_styles_dir(self) -> str:
        """Get the user styles directory based on platform."""
        if platform.system() == "Windows":
            appdata = os.environ.get("APPDATA", "")
            return os.path.join(appdata, "drawio-skill", "styles")
        else:
            home = os.path.expanduser("~")
            return os.path.join(home, ".drawio-skill", "styles")

    def _validate_preset(self, preset_data: Dict[str, Any]) -> bool:
        """Validate a preset JSON structure."""
        required_fields = ["name", "version", "palette", "roles", "shapes", "font", "edges"]
        for field in required_fields:
            if field not in preset_data:
                return False

        if preset_data.get("version") != 1:
            return False

        # Validate palette colors
        for slot, colors in preset_data.get("palette", {}).items():
            if colors:
                if not isinstance(colors.get("fillColor"), str) or not colors["fillColor"].startswith("#"):
                    return False
                if not isinstance(colors.get("strokeColor"), str) or not colors["strokeColor"].startswith("#"):
                    return False

        # Validate confidence if present
        if "confidence" in preset_data:
            if preset_data["confidence"] not in ["low", "medium", "high"]:
                return False

        return True

    def _load_preset_from_file(self, filepath: str) -> Optional[StylePreset]:
        """Load a preset from a JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not self._validate_preset(data):
                return None

            return StylePreset(data)
        except (json.JSONDecodeError, IOError):
            return None

    def load_all_presets(self) -> None:
        """Load all available presets from built-in and user directories."""
        self._presets = {}

        # Load built-in presets
        if os.path.isdir(self.builtin_dir):
            for filename in os.listdir(self.builtin_dir):
                if filename.endswith(".json"):
                    name = filename[:-5]  # Remove .json
                    filepath = os.path.join(self.builtin_dir, filename)
                    preset = self._load_preset_from_file(filepath)
                    if preset:
                        self._presets[name] = preset

        # Load user presets (override built-ins)
        if os.path.isdir(self.user_dir):
            for filename in os.listdir(self.user_dir):
                if filename.endswith(".json"):
                    name = filename[:-5]
                    filepath = os.path.join(self.user_dir, filename)
                    preset = self._load_preset_from_file(filepath)
                    if preset:
                        self._presets[name] = preset

                        # Check for default
                        if preset.default:
                            self._default_preset = preset

        # If no default was set, use the 'default' preset
        if not self._default_preset and "default" in self._presets:
            self._default_preset = self._presets["default"]

    def get_preset(self, name: Optional[str] = None) -> StylePreset:
        """Get a preset by name, or the default preset."""
        if not self._presets:
            self.load_all_presets()

        if name:
            name = name.lower()
            if name in self._presets:
                return self._presets[name]
            return self._default_preset or StylePreset({})

        return self._default_preset or StylePreset({})

    def list_presets(self) -> List[Dict[str, Any]]:
        """List all available presets with metadata."""
        if not self._presets:
            self.load_all_presets()

        result = []
        for name, preset in self._presets.items():
            result.append({
                "name": name,
                "location": "user" if self._is_user_preset(name) else "built-in",
                "source": preset.source,
                "confidence": preset.confidence,
                "default": preset.default,
            })
        return result

    def _is_user_preset(self, name: str) -> bool:
        """Check if a preset is a user preset."""
        filepath = os.path.join(self.user_dir, f"{name}.json")
        return os.path.isfile(filepath)

    def set_default_preset(self, name: str) -> bool:
        """Set a preset as the default."""
        name = name.lower()

        if not self._presets:
            self.load_all_presets()

        if name not in self._presets:
            return False

        # If it's a built-in, copy to user directory first
        if not self._is_user_preset(name):
            builtin_path = os.path.join(self.builtin_dir, f"{name}.json")
            user_path = os.path.join(self.user_dir, f"{name}.json")

            # Create user dir if needed
            os.makedirs(self.user_dir, exist_ok=True)

            # Copy the preset
            with open(builtin_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            data["default"] = True
            with open(user_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Reload
            self.load_all_presets()
            return True

        # It's already a user preset
        # Clear default flag from all other presets
        for preset_name, preset in self._presets.items():
            if preset._is_user_preset(preset_name):
                filepath = os.path.join(self.user_dir, f"{preset_name}.json")
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["default"] = (preset_name == name)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

        self.load_all_presets()
        return True

    def save_preset(self, name: str, preset_data: Dict[str, Any]) -> bool:
        """Save a preset to the user directory."""
        name = name.lower()

        # Validate first
        if not self._validate_preset(preset_data):
            return False

        # Ensure name matches
        preset_data["name"] = name

        # Create user dir if needed
        os.makedirs(self.user_dir, exist_ok=True)

        filepath = os.path.join(self.user_dir, f"{name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(preset_data, f, indent=2)

        # Reload
        self.load_all_presets()
        return True

    def delete_preset(self, name: str) -> bool:
        """Delete a user preset."""
        name = name.lower()

        if not self._is_user_preset(name):
            return False

        filepath = os.path.join(self.user_dir, f"{name}.json")
        os.remove(filepath)
        self.load_all_presets()
        return True


# Global singleton for convenience
_style_manager = None


def get_style_manager() -> StyleManager:
    """Get the global style manager instance."""
    global _style_manager
    if _style_manager is None:
        _style_manager = StyleManager()
        _style_manager.load_all_presets()
    return _style_manager


def get_default_preset() -> StylePreset:
    """Get the default style preset."""
    return get_style_manager().get_preset()


def get_preset_by_name(name: str) -> StylePreset:
    """Get a preset by name."""
    return get_style_manager().get_preset(name)

"""Configuration management for drawio-architect tools."""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path


@dataclass
class PathValidationConfig:
    """Configuration for path validation."""
    enabled: bool = True
    tolerance_percent: float = 10.0
    auto_fix: bool = False


@dataclass
class LayoutValidationConfig:
    """Configuration for layout validation."""
    enabled: bool = True
    overlap_tolerance: float = 5.0
    min_spacing: int = 50
    max_width: int = 850
    max_height: int = 1100
    edge_routing_orthogonal: bool = True


@dataclass
class SyncSettingsConfig:
    """Configuration for code synchronization."""
    auto_fix_paths: bool = True
    update_line_numbers: bool = True
    backup_original: bool = True
    backup_extension: str = ".bak"


@dataclass
class ToolConfig:
    """Complete tool configuration."""
    path_validation: PathValidationConfig = field(default_factory=PathValidationConfig)
    layout_validation: LayoutValidationConfig = field(default_factory=LayoutValidationConfig)
    sync_settings: SyncSettingsConfig = field(default_factory=SyncSettingsConfig)
    project_root: Optional[str] = None
    drawio_dir: Optional[str] = None


class ConfigManager:
    """Manages configuration for drawio-architect tools."""

    DEFAULT_CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config",
        "settings.json"
    )

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: Optional[ToolConfig] = None

    @property
    def config(self) -> ToolConfig:
        """Get the current configuration, loading from file if needed."""
        if self._config is None:
            self._config = self.load()
        return self._config

    def load(self) -> ToolConfig:
        """Load configuration from file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return self._parse_config(data)
            except (json.JSONDecodeError, IOError):
                pass

        return ToolConfig()

    def _parse_config(self, data: Dict[str, Any]) -> ToolConfig:
        """Parse configuration data into ToolConfig."""
        path_validation = PathValidationConfig(
            enabled=data.get("path_validation", {}).get("enabled", True),
            tolerance_percent=data.get("path_validation", {}).get("tolerance_percent", 10.0),
            auto_fix=data.get("path_validation", {}).get("auto_fix", False)
        )

        layout_validation = LayoutValidationConfig(
            enabled=data.get("layout_validation", {}).get("enabled", True),
            overlap_tolerance=data.get("layout_validation", {}).get("overlap_tolerance", 5.0),
            min_spacing=data.get("layout_validation", {}).get("min_spacing", 50),
            max_width=data.get("layout_validation", {}).get("max_width", 850),
            max_height=data.get("layout_validation", {}).get("max_height", 1100),
            edge_routing_orthogonal=data.get("layout_validation", {}).get("edge_routing_orthogonal", True)
        )

        sync_settings = SyncSettingsConfig(
            auto_fix_paths=data.get("sync_settings", {}).get("auto_fix_paths", True),
            update_line_numbers=data.get("sync_settings", {}).get("update_line_numbers", True),
            backup_original=data.get("sync_settings", {}).get("backup_original", True),
            backup_extension=data.get("sync_settings", {}).get("backup_extension", ".bak")
        )

        return ToolConfig(
            path_validation=path_validation,
            layout_validation=layout_validation,
            sync_settings=sync_settings,
            project_root=data.get("project_root"),
            drawio_dir=data.get("drawio_dir")
        )

    def save(self, config: Optional[ToolConfig] = None) -> None:
        """Save configuration to file."""
        if config is None:
            config = self._config or ToolConfig()

        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        data = {
            "path_validation": asdict(config.path_validation),
            "layout_validation": asdict(config.layout_validation),
            "sync_settings": asdict(config.sync_settings)
        }

        if config.project_root:
            data["project_root"] = config.project_root
        if config.drawio_dir:
            data["drawio_dir"] = config.drawio_dir

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def update(self, **kwargs) -> ToolConfig:
        """Update configuration values."""
        if self._config is None:
            self._config = self.load()

        if "project_root" in kwargs:
            self._config.project_root = kwargs["project_root"]
        if "drawio_dir" in kwargs:
            self._config.drawio_dir = kwargs["drawio_dir"]

        for section in ["path_validation", "layout_validation", "sync_settings"]:
            if section in kwargs:
                section_data = kwargs[section]
                current_section = getattr(self._config, section)

                for key, value in section_data.items():
                    if hasattr(current_section, key):
                        setattr(current_section, key, value)

        return self._config

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self.config)


def load_config(config_path: Optional[str] = None) -> ToolConfig:
    """Convenience function to load configuration."""
    manager = ConfigManager(config_path)
    return manager.config


def get_default_config() -> ToolConfig:
    """Get default configuration."""
    return ToolConfig()

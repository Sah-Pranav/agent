import os
import yaml
from pathlib import Path
from typing import Dict, Any, List

class AppConfig:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._data = self._load_config()
        self._load_env()
        
    def _load_config(self) -> Dict[str, Any]:
        """Load YAML configuration."""
        if not os.path.exists(self.config_path):
            return {}
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f) or {}

    def _load_env(self):
        """Load environment variables (handled by python-dotenv in entry point usually, but good to ensure)."""
        pass # Assumes dotenv loaded before init

    @property
    def target_prompt_count(self) -> int:
        return self._data.get("target_prompt_count", 0)

    @property
    def configs(self) -> List[Dict[str, Any]]:
        return self._data.get("configs", [])
    
    @property
    def template_id(self) -> str:
        return "nicegui_agent"
        
    @property
    def template_path(self) -> str:
        return "agent/nicegui_agent/template"

    @property
    def logs_dir(self) -> Path:
        return Path("logs_summary")

    @property
    def generated_apps_dir(self) -> Path:
        return Path("generated_apps")

    @property
    def metrics_file(self) -> Path:
        return Path("metrics_summary.csv")

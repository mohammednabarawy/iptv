import os
import json
from typing import Dict, Any

class ConfigManager:
    """Manage application configuration with default settings and user overrides"""
    
    DEFAULT_CONFIG = {
        "channel_check": {
            "timeout": 5,
            "max_retries": 3,
            "verify_ssl": False
        },
        "ui": {
            "theme": "light",  # Default to light theme
            "font_size": 10
        },
        "network": {
            "proxy": None,
            "user_agent": "IPTVGenerator/1.0"
        },
        "paths": {
            "cache_dir": os.path.join(os.path.expanduser("~"), ".iptv_generator", "cache"),
            "log_dir": os.path.join(os.path.expanduser("~"), ".iptv_generator", "logs")
        }
    }
    
    def __init__(self, config_path=None):
        """
        Initialize configuration manager
        
        :param config_path: Path to user configuration file
        """
        self.config_path = config_path or os.path.join(
            os.path.expanduser("~"), ".iptv_generator", "config.json"
        )
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file, merging with defaults
        
        :return: Merged configuration dictionary
        """
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    user_config = json.load(f)
                    
                # Deep merge of user config with defaults
                return self._deep_merge(self.DEFAULT_CONFIG, user_config)
            else:
                # Create default config file if it doesn't exist
                self.save_config(self.DEFAULT_CONFIG)
                return self.DEFAULT_CONFIG
        except Exception as e:
            print(f"Error loading config: {e}. Using default configuration.")
            return self.DEFAULT_CONFIG
    
    def save_config(self, config: Dict[str, Any]):
        """
        Save configuration to file
        
        :param config: Configuration dictionary to save
        """
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get(self, key: str, default=None):
        """
        Get a configuration value
        
        :param key: Dot-separated key path
        :param default: Default value if key not found
        :return: Configuration value
        """
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """
        Recursively merge two dictionaries
        
        :param base: Base dictionary
        :param update: Dictionary to update base with
        :return: Merged dictionary
        """
        result = base.copy()
        for k, v in update.items():
            if isinstance(v, dict):
                result[k] = self._deep_merge(result.get(k, {}), v)
            else:
                result[k] = v
        return result

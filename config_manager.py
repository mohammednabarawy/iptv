import os
import json
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    """Configuration manager for IPTV Manager application"""
    
    def __init__(self, config_file="config.json"):
        """Initialize configuration manager"""
        self.config_file = config_file
        self.config = self._load_config()
        
    def _load_config(self):
        """Load configuration from file"""
        try:
            # Create default config if file doesn't exist
            if not os.path.exists(self.config_file):
                return self._create_default_config()
                
            # Load existing config
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                
            logger.info(f"Loaded configuration from {self.config_file}")
            return config
            
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}", exc_info=True)
            return self._create_default_config()
            
    def _create_default_config(self):
        """Create default configuration"""
        try:
            default_config = {
                'ui.theme': 'light',
                'pagination.page_size': 100,
                'check.timeout': 3,
                'check.concurrent_requests': 20,
                'paths.m3u_output': 'playlist.m3u',
                'paths.epg_output': 'guide.xml',
                'features.auto_check': False,
                'features.auto_load_epg': True
            }
            
            # Save default config
            self._save_config(default_config)
            
            logger.info("Created default configuration")
            return default_config
            
        except Exception as e:
            logger.error(f"Error creating default configuration: {str(e)}", exc_info=True)
            return {}
            
    def _save_config(self, config=None):
        """Save configuration to file"""
        try:
            if config is None:
                config = self.config
                
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
                
            logger.info(f"Saved configuration to {self.config_file}")
            
        except Exception as e:
            logger.error(f"Error saving configuration: {str(e)}", exc_info=True)
            
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
        
    def set(self, key, value):
        """Set configuration value"""
        try:
            self.config[key] = value
            self._save_config()
            return True
            
        except Exception as e:
            logger.error(f"Error setting configuration value: {str(e)}", exc_info=True)
            return False
            
    def get_all(self):
        """Get all configuration values"""
        return self.config.copy()

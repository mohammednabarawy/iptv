import json
import os
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional

class DataManager:
    def __init__(self, data_dir: str = "y:/videos/iptv/data"):
        self.data_dir = data_dir
        self.channels_file = os.path.join(data_dir, "channels.json")
        self.epg_file = os.path.join(data_dir, "epg_data.json")
        self.metadata_file = os.path.join(data_dir, "metadata.json")
        
        # Create data directory if it doesn't exist
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        # Initialize logging
        self.logger = logging.getLogger(__name__)

    def save_channels(self, channels: List[Dict]) -> None:
        """Save channels data to JSON file"""
        try:
            # Convert Channel objects to dictionaries
            channels_data = []
            for channel in channels:
                channel_dict = {
                    'name': channel.get('name', ''),
                    'group': channel.get('group', ''),
                    'tvg_id': channel.get('tvg_id', ''),
                    'url': channel.get('url', ''),
                    'tvg_name': channel.get('tvg_name', ''),
                    'tvg_logo': channel.get('tvg_logo', ''),
                    'has_epg': channel.get('has_epg', False),
                    'is_working': channel.get('is_working', None)
                }
                channels_data.append(channel_dict)

            with open(self.channels_file, 'w', encoding='utf-8') as f:
                json.dump(channels_data, f, ensure_ascii=False, indent=2)
                
            # Update metadata
            self._update_metadata('channels_last_updated', datetime.now().isoformat())
            self.logger.info(f"Successfully saved {len(channels_data)} channels to {self.channels_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving channels: {str(e)}", exc_info=True)
            raise

    def load_channels(self) -> Optional[List[Dict]]:
        """Load channels data from JSON file"""
        try:
            if os.path.exists(self.channels_file):
                self.logger.info(f"Loading channels from {self.channels_file}")
                start_time = time.time()
                
                with open(self.channels_file, 'r', encoding='utf-8') as f:
                    channels = json.load(f)
                    
                self.logger.info(f"Loaded {len(channels)} channels in {time.time() - start_time:.2f} seconds")
                return channels
                
            self.logger.info("No channels file found")
            return None
            
        except Exception as e:
            self.logger.error(f"Error loading channels: {str(e)}", exc_info=True)
            return None

    def save_epg_data(self, epg_data: Dict) -> None:
        """Save EPG data to JSON file"""
        try:
            with open(self.epg_file, 'w', encoding='utf-8') as f:
                json.dump(epg_data, f, ensure_ascii=False, indent=2)
                
            # Update metadata
            self._update_metadata('epg_last_updated', datetime.now().isoformat())
            self.logger.info(f"Successfully saved EPG data to {self.epg_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving EPG data: {str(e)}", exc_info=True)
            raise

    def load_epg_data(self) -> Optional[Dict]:
        """Load EPG data from JSON file"""
        try:
            if os.path.exists(self.epg_file):
                self.logger.info(f"Loading EPG data from {self.epg_file}")
                start_time = time.time()
                
                with open(self.epg_file, 'r', encoding='utf-8') as f:
                    epg_data = json.load(f)
                    
                self.logger.info(f"Loaded EPG data with {len(epg_data)} entries in {time.time() - start_time:.2f} seconds")
                return epg_data
                
            self.logger.info("No EPG file found")
            return None
            
        except Exception as e:
            self.logger.error(f"Error loading EPG data: {str(e)}", exc_info=True)
            return None

    def _update_metadata(self, key: str, value: str) -> None:
        """Update metadata file with timestamp"""
        try:
            metadata = {}
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            
            metadata[key] = value
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            self.logger.info(f"Successfully updated metadata file {self.metadata_file}")
            
        except Exception as e:
            self.logger.error(f"Error updating metadata: {str(e)}", exc_info=True)
            raise

    def get_last_update_time(self, data_type: str) -> Optional[datetime]:
        """Get last update time for specified data type"""
        try:
            if os.path.exists(self.metadata_file):
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    key = f'{data_type}_last_updated'
                    if key in metadata:
                        return datetime.fromisoformat(metadata[key])
            return None
        except Exception as e:
            self.logger.error(f"Error getting last update time: {str(e)}", exc_info=True)
            return None

    def clear_data(self) -> None:
        """Clear all saved data"""
        try:
            for file in [self.channels_file, self.epg_file, self.metadata_file]:
                if os.path.exists(file):
                    os.remove(file)
            self.logger.info("Successfully cleared all saved data")
            
        except Exception as e:
            self.logger.error(f"Error clearing data: {str(e)}", exc_info=True)
            raise

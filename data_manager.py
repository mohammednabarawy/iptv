import sqlite3
import json
import os
import logging
import time
import shutil
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager

class DataManager:
    def __init__(self, data_dir: str = "y:/videos/iptv/data"):
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "iptv.db")
        
        # Keep track of old JSON files for migration
        self.channels_file = os.path.join(data_dir, "channels.json")
        self.epg_file = os.path.join(data_dir, "epg_data.json")
        self.metadata_file = os.path.join(data_dir, "metadata.json")
        
        # Create data directory if it doesn't exist
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        # Initialize logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize database and migrate data if needed
        print("Initializing database...")
        self._init_db()
        if not self._is_data_migrated():
            print("Starting data migration...")
            self._backup_json_data()
            self._migrate_to_sqlite()
            print("Migration completed!")
    
    def _backup_json_data(self) -> str:
        """Create backup of JSON files before migration"""
        backup_dir = os.path.join(self.data_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(backup_dir, exist_ok=True)
        
        # Files to backup
        files_to_backup = ["channels.json", "epg_data.json", "metadata.json"]
        
        # Copy each file to backup directory
        for file_name in files_to_backup:
            src_path = os.path.join(self.data_dir, file_name)
            if os.path.exists(src_path):
                shutil.copy2(src_path, os.path.join(backup_dir, file_name))
                print(f"Backed up {file_name}")
        
        return backup_dir
    
    def _is_data_migrated(self) -> bool:
        """Check if data has been migrated to SQLite"""
        if not os.path.exists(self.db_path):
            return False
            
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM metadata WHERE key = 'migration_completed'")
                result = cursor.fetchone()
                return bool(result)
        except:
            return False
    
    def _migrate_to_sqlite(self) -> None:
        """Migrate data from JSON files to SQLite database"""
        try:
            # Load existing JSON data
            channels = []
            if os.path.exists(self.channels_file):
                print("Loading channels from JSON...")
                with open(self.channels_file, 'r', encoding='utf-8') as f:
                    channels = json.load(f)
            
            epg_data = {}
            if os.path.exists(self.epg_file):
                print("Loading EPG data from JSON...")
                with open(self.epg_file, 'r', encoding='utf-8') as f:
                    epg_data = json.load(f)
            
            # Save to SQLite
            if channels:
                print(f"Migrating {len(channels)} channels to SQLite...")
                self.save_channels(channels)
            if epg_data:
                print(f"Migrating EPG data with {len(epg_data)} entries to SQLite...")
                self.save_epg_data(epg_data)
            
            # Mark migration as completed
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO metadata (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, ('migration_completed', 'true'))
                conn.commit()
            
            print("Successfully migrated data to SQLite")
            
        except Exception as e:
            print(f"Error during migration: {str(e)}")
            raise
    
    @contextmanager
    def _get_db(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database tables"""
        with self._get_db() as conn:
            cursor = conn.cursor()
            
            # Create channels table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    url TEXT PRIMARY KEY,
                    name TEXT,
                    group_title TEXT,
                    tvg_id TEXT,
                    tvg_name TEXT,
                    tvg_logo TEXT,
                    has_epg BOOLEAN,
                    is_working BOOLEAN,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create EPG data table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS epg_data (
                    channel_id TEXT PRIMARY KEY,
                    data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            print("Database tables created successfully")
    
    def save_channels(self, channels: List[Dict]) -> None:
        """Save channels data to database using batch operations"""
        try:
            start_time = time.time()
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION")
                
                # Batch insert in chunks of 1000
                batch_size = 1000
                for i in range(0, len(channels), batch_size):
                    batch = channels[i:i + batch_size]
                    batch_data = [(
                        ch.get('url', ''),
                        ch.get('name', ''),
                        ch.get('group', ''),
                        ch.get('tvg_id', ''),
                        ch.get('tvg_name', ''),
                        ch.get('tvg_logo', ''),
                        ch.get('has_epg', False),
                        ch.get('is_working', None)
                    ) for ch in batch]
                    
                    cursor.executemany("""
                        INSERT OR REPLACE INTO channels (
                            url, name, group_title, tvg_id, tvg_name,
                            tvg_logo, has_epg, is_working, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, batch_data)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO metadata (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, ('channels_last_updated', datetime.now().isoformat()))
                
                conn.commit()
            
            elapsed = time.time() - start_time
            print(f"Successfully saved {len(channels)} channels to database in {elapsed:.2f} seconds")
            
        except Exception as e:
            print(f"Error saving channels: {str(e)}")
            raise
    
    def load_channels(self) -> Optional[List[Dict]]:
        """Load channels data from database"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                start_time = time.time()
                cursor.execute("SELECT * FROM channels")
                rows = cursor.fetchall()
                
                if not rows:
                    print("No channels found in database")
                    return None
                
                channels = []
                for row in rows:
                    channel = {
                        'name': row['name'],
                        'url': row['url'],
                        'group': row['group_title'],
                        'tvg_id': row['tvg_id'],
                        'tvg_name': row['tvg_name'],
                        'tvg_logo': row['tvg_logo'],
                        'has_epg': bool(row['has_epg']),
                        'is_working': row['is_working']
                    }
                    channels.append(channel)
                
                print(f"Loaded {len(channels)} channels in {time.time() - start_time:.2f} seconds")
                return channels
                
        except Exception as e:
            print(f"Error loading channels: {str(e)}")
            return None
    
    def save_epg_data(self, epg_data: Dict) -> None:
        """Save EPG data to database"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                cursor.execute("BEGIN TRANSACTION")
                
                # Clear existing EPG data
                cursor.execute("DELETE FROM epg_data")
                
                # Insert new EPG data
                for channel_id, data in epg_data.items():
                    try:
                        json_data = json.dumps(data)
                        cursor.execute("""
                            INSERT INTO epg_data (channel_id, data, updated_at)
                            VALUES (?, ?, CURRENT_TIMESTAMP)
                        """, (channel_id, json_data))
                    except (TypeError, json.JSONEncodeError) as e:
                        self.logger.warning(f"Failed to encode EPG data for channel {channel_id}: {str(e)}")
                        continue
                
                # Update metadata
                cursor.execute("""
                    INSERT OR REPLACE INTO metadata (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, ('epg_last_updated', datetime.now().isoformat()))
                
                conn.commit()
                
            print(f"Successfully saved EPG data with {len(epg_data)} entries")
            
        except Exception as e:
            print(f"Error saving EPG data: {str(e)}")
            raise
    
    def load_epg_data(self) -> Optional[Dict]:
        """Load EPG data from database"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                start_time = time.time()
                cursor.execute("SELECT * FROM epg_data")
                rows = cursor.fetchall()
                
                if not rows:
                    print("No EPG data found in database")
                    return None
                
                epg_data = {}
                for row in rows:
                    try:
                        epg_data[row['channel_id']] = json.loads(row['data'])
                    except json.JSONDecodeError:
                        self.logger.warning(f"Failed to decode EPG data for channel {row['channel_id']}")
                        continue
                
                print(f"Loaded EPG data with {len(epg_data)} entries in {time.time() - start_time:.2f} seconds")
                return epg_data
                
        except Exception as e:
            print(f"Error loading EPG data: {str(e)}")
            return None
    
    def update_channel_status(self, url: str, is_working: bool) -> None:
        """Update the working status of a channel"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE channels
                    SET is_working = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE url = ?
                """, (is_working, url))
                conn.commit()
                
            print(f"Updated status for channel {url}: is_working={is_working}")
            
        except Exception as e:
            print(f"Error updating channel status: {str(e)}")
            raise
    
    def get_last_update_time(self, data_type: str) -> Optional[datetime]:
        """Get last update time for specified data type"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT value FROM metadata
                    WHERE key = ?
                """, (f'{data_type}_last_updated',))
                
                row = cursor.fetchone()
                if row:
                    return datetime.fromisoformat(row['value'])
                return None
                
        except Exception as e:
            print(f"Error getting last update time: {str(e)}")
            return None

if __name__ == "__main__":
    # Initialize database
    print("\nStarting database initialization and migration...")
    data_manager = DataManager()
    
    # Test database by loading channels
    print("\nTesting database by loading channels...")
    channels = data_manager.load_channels()
    if channels:
        print(f"Successfully loaded {len(channels)} channels from database")
    
    print("\nDatabase initialization and testing complete!")
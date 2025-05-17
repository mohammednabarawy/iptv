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
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # Use relative path from the script location
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(script_dir, "data")
            
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
        print(f"Initializing database at {self.db_path}...")
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
        """Context manager for database connections with optimized settings"""
        conn = None
        try:
            # Create connection
            conn = sqlite3.connect(self.db_path)
            # Configure connection to return rows as dictionaries
            conn.row_factory = sqlite3.Row
            # Optimize database performance
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA busy_timeout = 5000")  # 5 seconds timeout
            
            yield conn
        finally:
            if conn:
                conn.close()
    
    def _init_db(self):
        """Initialize database tables"""
        try:
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
                        resolution TEXT,
                        content_type TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Check if we need to add columns to existing table
                try:
                    cursor.execute("SELECT resolution FROM channels LIMIT 1")
                except sqlite3.OperationalError:
                    # Add missing columns
                    self.logger.info("Adding resolution column to channels table")
                    cursor.execute("ALTER TABLE channels ADD COLUMN resolution TEXT")
                
                try:
                    cursor.execute("SELECT content_type FROM channels LIMIT 1")
                except sqlite3.OperationalError:
                    # Add missing columns
                    self.logger.info("Adding content_type column to channels table")
                    cursor.execute("ALTER TABLE channels ADD COLUMN content_type TEXT")
                
                # Create indexes for faster searches
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_group ON channels(group_title)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_working ON channels(is_working)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_epg ON channels(has_epg)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_tvg_id ON channels(tvg_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_resolution ON channels(resolution)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_content_type ON channels(content_type)")
                
                # Create compound indexes for common filter combinations
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_working ON channels(group_title, is_working)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_name_working ON channels(name, is_working)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_resolution_working ON channels(resolution, is_working)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_type_working ON channels(content_type, is_working)")
                
                # Create metadata table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create favorites table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS favorites (
                        channel_url TEXT PRIMARY KEY,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (channel_url) REFERENCES channels(url) ON DELETE CASCADE
                    )
                """)
                
                # Create watch history table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS watch_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_url TEXT,
                        watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        duration INTEGER DEFAULT 0,
                        FOREIGN KEY (channel_url) REFERENCES channels(url) ON DELETE CASCADE
                    )
                """)
                
                # Create index on watch history
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_channel ON watch_history(channel_url)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_time ON watch_history(watched_at)")
                
                
                # Optimize database settings
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
                cursor.execute("PRAGMA cache_size = 10000")
                cursor.execute("PRAGMA temp_store = MEMORY")
                cursor.execute("PRAGMA mmap_size = 30000000000")
                
                conn.commit()
                self.logger.info("Database initialized successfully")
        except Exception as e:
            self.logger.error(f"Error initializing database: {str(e)}")
            raise
    
    def save_channels(self, channels: List[Dict]) -> None:
        """Save channels data to database using batch operations"""
        try:
            start_time = time.time()
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                # Begin transaction for better performance
                cursor.execute("BEGIN TRANSACTION")
                
                # Use executemany for better performance
                batch_data = [(
                    ch.get('url', ''),
                    ch.get('name', ''),
                    ch.get('group', ''),
                    ch.get('tvg_id', ''),
                    ch.get('tvg_name', ''),
                    ch.get('tvg_logo', ''),
                    ch.get('has_epg', False),
                    ch.get('is_working', None)
                ) for ch in channels]
                
                # Use INSERT OR REPLACE to handle both new and existing channels
                # Process in batches of 1000 for better memory management
                batch_size = 1000
                for i in range(0, len(batch_data), batch_size):
                    batch = batch_data[i:i+batch_size]
                    cursor.executemany("""
                        INSERT OR REPLACE INTO channels 
                        (url, name, group_title, tvg_id, tvg_name, tvg_logo, has_epg, is_working) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch)
                    self.logger.debug(f"Processed batch {i//batch_size + 1} of {(len(batch_data) + batch_size - 1)//batch_size}")
                
                # Commit transaction
                conn.commit()
                self.logger.info(f"Saved {len(channels)} channels to database")
            
            elapsed = time.time() - start_time
            print(f"Successfully saved {len(channels)} channels to database in {elapsed:.2f} seconds")
        except Exception as e:
            self.logger.error(f"Error saving channels: {str(e)}")
            raise
    
    def get_channel_count(self, filters=None):
        """Get the total count of channels, optionally with filters"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                if filters:
                    # Build WHERE clause based on filters
                    where_clauses = []
                    params = []
                    
                    for field, value in filters.items():
                        if field == 'name':
                            # Support for boolean operators in search
                            if ' AND ' in value:
                                search_terms = value.split(' AND ')
                                for term in search_terms:
                                    term = term.strip()
                                    where_clauses.append("name LIKE ?")
                                    params.append(f"%{term}%")
                            elif ' OR ' in value:
                                search_terms = value.split(' OR ')
                                or_conditions = []
                                for term in search_terms:
                                    term = term.strip()
                                    or_conditions.append("name LIKE ?")
                                    params.append(f"%{term}%")
                                where_clauses.append(f"({' OR '.join(or_conditions)})")
                            elif value.startswith('NOT '):
                                term = value[4:].strip()
                                where_clauses.append("name NOT LIKE ?")
                                params.append(f"%{term}%")
                            else:
                                where_clauses.append("name LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'group_title':
                            # Handle complex group_title filtering with OR conditions
                            if '|' in value:
                                # Multiple values separated by pipe
                                group_conditions = []
                                for group_val in value.split('|'):
                                    group_conditions.append("group_title LIKE ?")
                                    params.append(f"%{group_val.strip()}%")
                                where_clauses.append(f"({' OR '.join(group_conditions)})")
                            else:
                                where_clauses.append("group_title LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'tvg_id':
                            where_clauses.append("tvg_id LIKE ?")
                            params.append(f"%{value}%")
                        elif field == 'is_working':
                            where_clauses.append("is_working = ?")
                            params.append(1 if value else 0)
                        elif field == 'has_epg':
                            where_clauses.append("has_epg = ?")
                            params.append(1 if value else 0)
                        elif field == 'resolution':
                            # Handle resolution filtering
                            if value == 'SD':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ? OR resolution IS NULL)")
                                params.append('%480p%')
                                params.append('%576p%')
                            elif value == 'HD':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ?)")
                                params.append('%720p%')
                                params.append('%1080p%')
                            elif value == 'FHD':
                                where_clauses.append("resolution LIKE ?")
                                params.append('%1080p%')
                            elif value == '4K':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ?)")
                                params.append('%2160p%')
                                params.append('%4K%')
                            else:
                                where_clauses.append("resolution LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'content_type':
                            where_clauses.append("content_type LIKE ?")
                            params.append(f"%{value}%")
                    
                    if where_clauses:
                        query = f"SELECT COUNT(*) FROM channels WHERE {' AND '.join(where_clauses)}"
                        self.logger.debug(f"Count query: {query} with params {params}")
                        cursor.execute(query, params)
                    else:
                        cursor.execute("SELECT COUNT(*) FROM channels")
                else:
                    cursor.execute("SELECT COUNT(*) FROM channels")
                
                count = cursor.fetchone()[0]
                self.logger.debug(f"Total count: {count}")
                return count
        except Exception as e:
            self.logger.error(f"Error getting channel count: {str(e)}")
            return 0
    
    def load_channels(self, limit=None, offset=None, filters=None):
        """Load channels from the database with pagination and filtering support"""
        try:
            start_time = time.time()
            with self._get_db() as conn:
                cursor = conn.cursor()
                
                # Start building the query
                query = "SELECT * FROM channels"
                params = []
                
                # Add filters if provided
                if filters:
                    where_clauses = []
                    
                    for field, value in filters.items():
                        if field == 'name':
                            # Support for boolean operators in search
                            if ' AND ' in value:
                                search_terms = value.split(' AND ')
                                for term in search_terms:
                                    term = term.strip()
                                    where_clauses.append("name LIKE ?")
                                    params.append(f"%{term}%")
                            elif ' OR ' in value:
                                search_terms = value.split(' OR ')
                                or_conditions = []
                                for term in search_terms:
                                    term = term.strip()
                                    or_conditions.append("name LIKE ?")
                                    params.append(f"%{term}%")
                                where_clauses.append(f"({' OR '.join(or_conditions)})")
                            elif value.startswith('NOT '):
                                term = value[4:].strip()
                                where_clauses.append("name NOT LIKE ?")
                                params.append(f"%{term}%")
                            else:
                                where_clauses.append("name LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'group_title':
                            # Handle complex group_title filtering with OR conditions
                            if '|' in value:
                                # Multiple values separated by pipe
                                group_conditions = []
                                for group_val in value.split('|'):
                                    group_conditions.append("group_title LIKE ?")
                                    params.append(f"%{group_val.strip()}%")
                                where_clauses.append(f"({' OR '.join(group_conditions)})")
                            else:
                                where_clauses.append("group_title LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'tvg_id':
                            where_clauses.append("tvg_id LIKE ?")
                            params.append(f"%{value}%")
                        elif field == 'is_working':
                            where_clauses.append("is_working = ?")
                            params.append(1 if value else 0)
                        elif field == 'has_epg':
                            where_clauses.append("has_epg = ?")
                            params.append(1 if value else 0)
                        elif field == 'resolution':
                            # Handle resolution filtering
                            if value == 'SD':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ? OR resolution IS NULL)")
                                params.append('%480p%')
                                params.append('%576p%')
                            elif value == 'HD':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ?)")
                                params.append('%720p%')
                                params.append('%1080p%')
                            elif value == 'FHD':
                                where_clauses.append("resolution LIKE ?")
                                params.append('%1080p%')
                            elif value == '4K':
                                where_clauses.append("(resolution LIKE ? OR resolution LIKE ?)")
                                params.append('%2160p%')
                                params.append('%4K%')
                            else:
                                where_clauses.append("resolution LIKE ?")
                                params.append(f"%{value}%")
                        elif field == 'content_type':
                            where_clauses.append("content_type LIKE ?")
                            params.append(f"%{value}%")
                    
                    if where_clauses:
                        query += f" WHERE {' AND '.join(where_clauses)}"
                
                # Add pagination if provided
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                    
                    if offset is not None:
                        query += " OFFSET ?"
                        params.append(offset)
                
                # Execute the query
                self.logger.debug(f"Query: {query} with params {params}")
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                # Convert to list of dictionaries
                channels = []
                for row in rows:
                    channel = {
                        'url': row['url'],
                        'name': row['name'],
                        'group_title': row['group_title'],  # Use consistent field name
                        'tvg_id': row['tvg_id'],
                        'tvg_name': row['tvg_name'],
                        'tvg_logo': row['tvg_logo'],
                        'has_epg': bool(row['has_epg']),
                        'is_working': bool(row['is_working']) if row['is_working'] is not None else None,
                        'resolution': row['resolution'] if 'resolution' in row else None,
                        'content_type': row['content_type'] if 'content_type' in row else None
                    }
                    channels.append(channel)
                
                elapsed = time.time() - start_time
                self.logger.debug(f"Loaded {len(channels)} channels in {elapsed:.3f}s")
                return channels
        except Exception as e:
            self.logger.error(f"Error loading channels: {str(e)}")
            return []
    
    def add_to_favorites(self, channel_url: str) -> bool:
        """Add a channel to favorites"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO favorites (channel_url) VALUES (?)",
                    (channel_url,)
                )
                return True
        except Exception as e:
            self.logger.error(f"Error adding channel to favorites: {str(e)}")
            return False
    
    def remove_from_favorites(self, channel_url: str) -> bool:
        """Remove a channel from favorites"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM favorites WHERE channel_url = ?",
                    (channel_url,)
                )
                return True
        except Exception as e:
            self.logger.error(f"Error removing channel from favorites: {str(e)}")
            return False
    
    def get_favorites(self, limit: int = None, offset: int = None) -> List[Dict]:
        """Get list of favorite channels"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT c.*, f.added_at 
                    FROM channels c
                    JOIN favorites f ON c.url = f.channel_url
                    ORDER BY f.added_at DESC
                """
                params = []
                
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                    
                    if offset is not None:
                        query += " OFFSET ?"
                        params.append(offset)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                favorites = []
                for row in rows:
                    channel = {
                        'url': row['url'],
                        'name': row['name'],
                        'group_title': row['group_title'],
                        'tvg_id': row['tvg_id'],
                        'tvg_name': row['tvg_name'],
                        'tvg_logo': row['tvg_logo'],
                        'has_epg': bool(row['has_epg']),
                        'is_working': bool(row['is_working']) if row['is_working'] is not None else None,
                        'resolution': row['resolution'] if 'resolution' in row else None,
                        'content_type': row['content_type'] if 'content_type' in row else None,
                        'added_at': row['added_at']
                    }
                    favorites.append(channel)
                
                return favorites
        except Exception as e:
            self.logger.error(f"Error getting favorites: {str(e)}")
            return []
    
    def is_favorite(self, channel_url: str) -> bool:
        """Check if a channel is in favorites"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM favorites WHERE channel_url = ?",
                    (channel_url,)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Error checking if channel is favorite: {str(e)}")
            return False
    
    def add_to_watch_history(self, channel_url: str, duration: int = 0) -> bool:
        """Add a channel to watch history"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO watch_history (channel_url, duration) VALUES (?, ?)",
                    (channel_url, duration)
                )
                return True
        except Exception as e:
            self.logger.error(f"Error adding channel to watch history: {str(e)}")
            return False
    
    def get_watch_history(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        """Get watch history"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT c.*, h.watched_at, h.duration 
                    FROM channels c
                    JOIN watch_history h ON c.url = h.channel_url
                    ORDER BY h.watched_at DESC
                """
                params = []
                
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                    
                    if offset is not None:
                        query += " OFFSET ?"
                        params.append(offset)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    channel = {
                        'url': row['url'],
                        'name': row['name'],
                        'group_title': row['group_title'],
                        'tvg_id': row['tvg_id'],
                        'tvg_name': row['tvg_name'],
                        'tvg_logo': row['tvg_logo'],
                        'has_epg': bool(row['has_epg']),
                        'is_working': bool(row['is_working']) if row['is_working'] is not None else None,
                        'resolution': row['resolution'] if 'resolution' in row else None,
                        'content_type': row['content_type'] if 'content_type' in row else None,
                        'watched_at': row['watched_at'],
                        'duration': row['duration']
                    }
                    history.append(channel)
                
                return history
        except Exception as e:
            self.logger.error(f"Error getting watch history: {str(e)}")
            return []
    
    def get_channel_statistics(self) -> Dict:
        """Get statistics about the channel collection"""
        try:
            with self._get_db() as conn:
                cursor = conn.cursor()
                stats = {}
                
                # Total channels
                cursor.execute("SELECT COUNT(*) FROM channels")
                stats['total_channels'] = cursor.fetchone()[0]
                
                # Working channels
                cursor.execute("SELECT COUNT(*) FROM channels WHERE is_working = 1")
                stats['working_channels'] = cursor.fetchone()[0]
                
                # Channels with EPG
                cursor.execute("SELECT COUNT(*) FROM channels WHERE has_epg = 1")
                stats['channels_with_epg'] = cursor.fetchone()[0]
                
                # Channels by resolution
                cursor.execute("""
                    SELECT resolution, COUNT(*) as count 
                    FROM channels 
                    WHERE resolution IS NOT NULL 
                    GROUP BY resolution
                """)
                stats['resolution_counts'] = {row['resolution']: row['count'] for row in cursor.fetchall()}
                
                # Channels by content type
                cursor.execute("""
                    SELECT content_type, COUNT(*) as count 
                    FROM channels 
                    WHERE content_type IS NOT NULL 
                    GROUP BY content_type
                """)
                stats['content_type_counts'] = {row['content_type']: row['count'] for row in cursor.fetchall()}
                
                # Channels by group
                cursor.execute("""
                    SELECT group_title, COUNT(*) as count 
                    FROM channels 
                    GROUP BY group_title 
                    ORDER BY count DESC 
                    LIMIT 10
                """)
                stats['top_groups'] = {row['group_title']: row['count'] for row in cursor.fetchall()}
                
                # Favorite channels count
                cursor.execute("SELECT COUNT(*) FROM favorites")
                stats['favorite_channels'] = cursor.fetchone()[0]
                
                # Recently watched count
                cursor.execute("SELECT COUNT(DISTINCT channel_url) FROM watch_history")
                stats['watched_channels'] = cursor.fetchone()[0]
                
                return stats
        except Exception as e:
            self.logger.error(f"Error getting channel statistics: {str(e)}")
            return {}
    
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
        """Load EPG data from database with optimized performance"""
        try:
            with self._get_db() as conn:
                # Set optimized database parameters
                conn.execute("PRAGMA cache_size = -10000")  # Use 10MB cache
                conn.execute("PRAGMA temp_store = MEMORY")
                
                cursor = conn.cursor()
                
                start_time = time.time()
                
                # Only select the columns we need
                cursor.execute("SELECT channel_id, data FROM epg_data")
                
                # Process rows in batches
                epg_data = {}
                batch_size = 500
                rows = cursor.fetchmany(batch_size)
                
                while rows:
                    for row in rows:
                        try:
                            epg_data[row['channel_id']] = json.loads(row['data'])
                        except json.JSONDecodeError:
                            self.logger.warning(f"Failed to decode EPG data for channel {row['channel_id']}")
                            continue
                    rows = cursor.fetchmany(batch_size)
                
                if not epg_data:
                    print("No EPG data found in database")
                    return None
                
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
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QPushButton, QLabel, QProgressBar,
                           QTextEdit, QFileDialog, QMessageBox, QTabWidget,
                           QListWidget, QListWidgetItem, QFrame, QTableWidget,
                           QTableWidgetItem, QHeaderView, QLineEdit, QComboBox, 
                           QCheckBox, QGroupBox)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QMetaObject, Q_ARG, pyqtSlot,
                         QObject)
from PyQt5.QtGui import QIcon, QColor
import qtawesome as qta
import iptv_generator
import logging
import os
import concurrent.futures
import json
from data_manager import DataManager
import requests
import m3u8
from datetime import datetime, timedelta
import vlc
import time
from logger_config import setup_logger
import gzip
import xml.etree.ElementTree as ET
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from typing import Dict, Optional

# Set up logger
logger = setup_logger()

class Channel:
    """Represents an IPTV channel with its properties"""
    def __init__(self, name: str = "", url: str = "", group: str = "", 
                 tvg_id: str = "", tvg_name: str = "", tvg_logo: str = "",
                 has_epg: bool = False, is_working: Optional[bool] = None):
        self.name = name
        self.url = url
        self.group = group
        self.tvg_id = tvg_id
        self.tvg_name = tvg_name
        self.tvg_logo = tvg_logo
        self.has_epg = has_epg
        self.is_working = is_working

    def to_dict(self) -> Dict:
        """Convert channel to dictionary for JSON serialization"""
        return {
            'name': self.name,
            'url': self.url,
            'group': self.group,
            'tvg_id': self.tvg_id,
            'tvg_name': self.tvg_name,
            'tvg_logo': self.tvg_logo,
            'has_epg': self.has_epg,
            'is_working': self.is_working
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Channel':
        """Create Channel instance from dictionary"""
        return cls(
            name=data.get('name', ''),
            url=data.get('url', ''),
            group=data.get('group', ''),
            tvg_id=data.get('tvg_id', ''),
            tvg_name=data.get('tvg_name', ''),
            tvg_logo=data.get('tvg_logo', ''),
            has_epg=data.get('has_epg', False),
            is_working=data.get('is_working', None)
        )

    def __eq__(self, other):
        if not isinstance(other, Channel):
            return False
        return self.url == other.url

    def __hash__(self):
        return hash(self.url)

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread"""
    progress = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    result = pyqtSignal(object)

class WorkerThread(QThread):
    """Worker thread for running background tasks"""
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.result = None
        
        # Connect signals
        self.finished.connect(self.signals.finished)
        
        logger.debug(f"Created worker thread for function: {fn.__name__}")

    def run(self):
        try:
            logger.debug(f"Starting worker thread: {self.fn.__name__}")
            self.result = self.fn(*self.args, **self.kwargs)
            logger.debug(f"Worker thread completed: {self.fn.__name__}")
        except Exception as e:
            logger.error(f"Error in worker thread: {str(e)}", exc_info=True)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

class IPTVGeneratorGUI(QMainWindow):
    progress_signal = pyqtSignal(object)  # For progress updates
    check_progress = pyqtSignal(int)      # For progress bar updates
    log_signal = pyqtSignal(str)          # For log messages
    error_signal = pyqtSignal(str)        # For error messages

    def __init__(self):
        super().__init__()
        
        try:
            logger.info("Initializing main window")
            
            # Initialize UI
            self.init_ui()
            
            # Initialize data
            self.all_channels = []
            self.epg_data = {}
            self.channel_map = {}
            self.is_loading = False
            self.checkbox_column = 6  # Index of checkbox column
            
            # Create data manager
            self.data_manager = DataManager()
            
            # Connect signals
            self.search_input.textChanged.connect(self.apply_filters)
            self.category_combo.currentTextChanged.connect(self.apply_filters)
            self.country_edit.textChanged.connect(self.apply_filters)
            self.official_only.stateChanged.connect(self.apply_filters)
            
            self.select_all_button.clicked.connect(self.select_all_visible)
            self.deselect_all_button.clicked.connect(self.deselect_all)
            
            self.load_button.clicked.connect(self.load_channels)
            self.check_button.clicked.connect(self.check_selected_channels)
            self.generate_button.clicked.connect(self.generate)
            
            # Load saved data
            self.load_saved_data()
            
        except Exception as e:
            logger.error(f"Error initializing main window: {str(e)}", exc_info=True)
            raise

    def init_ui(self):
        """Initialize the user interface"""
        try:
            self.setWindowTitle("IPTV Channel Manager")
            self.setMinimumSize(1200, 800)
            self.setWindowIcon(qta.icon('fa5s.tv'))
            
            # Create main widget and layout
            main_widget = QWidget()
            self.setCentralWidget(main_widget)
            layout = QVBoxLayout(main_widget)
            
            # Create filter options group
            filter_group = QGroupBox("Filter Options")
            filter_layout = QHBoxLayout()
            
            # Search filter
            search_layout = QHBoxLayout()
            search_label = QLabel()
            search_label.setPixmap(qta.icon('fa5s.search').pixmap(16, 16))
            search_layout.addWidget(search_label)
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Search channels...")
            search_layout.addWidget(self.search_input)
            filter_layout.addLayout(search_layout)
            
            # Category filter
            category_layout = QHBoxLayout()
            category_label = QLabel()
            category_label.setPixmap(qta.icon('fa5s.tags').pixmap(16, 16))
            category_layout.addWidget(category_label)
            self.category_combo = QComboBox()
            self.category_combo.addItems(['All', 'Movies', 'Sports', 'News', 'Entertainment', 'Music'])
            category_layout.addWidget(self.category_combo)
            filter_layout.addLayout(category_layout)
            
            # Country filter
            country_layout = QHBoxLayout()
            country_label = QLabel()
            country_label.setPixmap(qta.icon('fa5s.globe').pixmap(16, 16))
            country_layout.addWidget(country_label)
            self.country_edit = QLineEdit()
            self.country_edit.setPlaceholderText("Enter country...")
            country_layout.addWidget(self.country_edit)
            filter_layout.addLayout(country_layout)
            
            # Official only filter
            self.official_only = QCheckBox("Official iptv.org only")
            self.official_only.setIcon(qta.icon('fa5s.check-circle'))
            filter_layout.addWidget(self.official_only)
            
            filter_group.setLayout(filter_layout)
            layout.addWidget(filter_group)
            
            # Create channels table
            self.channels_table = QTableWidget()
            self.table_columns = ["Name", "Group", "Country", "Source", "EPG", "Status", "Selected"]
            self.channels_table.setColumnCount(len(self.table_columns))
            self.channels_table.setHorizontalHeaderLabels(self.table_columns)
            
            # Set column resize modes
            self.channels_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for i in range(1, len(self.table_columns)):
                self.channels_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            
            # Enable sorting
            self.channels_table.setSortingEnabled(True)
            
            # Connect cell changed signal
            self.channels_table.cellChanged.connect(self.on_cell_changed)
            
            layout.addWidget(self.channels_table)
            
            # Selection buttons and count
            selection_layout = QHBoxLayout()
            
            count_label = QLabel()
            count_label.setPixmap(qta.icon('fa5s.list').pixmap(16, 16))
            selection_layout.addWidget(count_label)
            self.channel_count_label = QLabel("Channels: 0")
            selection_layout.addWidget(self.channel_count_label)
            
            selection_layout.addStretch()
            
            self.select_all_button = QPushButton("Select All")
            self.select_all_button.setIcon(qta.icon('fa5s.check-square'))
            selection_layout.addWidget(self.select_all_button)
            
            self.deselect_all_button = QPushButton("Deselect All")
            self.deselect_all_button.setIcon(qta.icon('fa5s.square'))
            selection_layout.addWidget(self.deselect_all_button)
            
            layout.addLayout(selection_layout)
            
            # Output Options Group
            output_group = QGroupBox("Output Options")
            output_layout = QVBoxLayout()
            
            # M3U output path
            m3u_layout = QHBoxLayout()
            m3u_label = QLabel()
            m3u_label.setPixmap(qta.icon('fa5s.file-video').pixmap(16, 16))
            m3u_layout.addWidget(m3u_label)
            m3u_layout.addWidget(QLabel("M3U Output:"))
            self.m3u_path = QLineEdit("merged_playlist.m3u")
            m3u_layout.addWidget(self.m3u_path)
            self.m3u_browse = QPushButton("Browse")
            self.m3u_browse.setIcon(qta.icon('fa5s.folder-open'))
            self.m3u_browse.clicked.connect(lambda: self.browse_file("M3U"))
            m3u_layout.addWidget(self.m3u_browse)
            output_layout.addLayout(m3u_layout)
            
            # EPG output path
            epg_layout = QHBoxLayout()
            epg_label = QLabel()
            epg_label.setPixmap(qta.icon('fa5s.calendar-alt').pixmap(16, 16))
            epg_layout.addWidget(epg_label)
            epg_layout.addWidget(QLabel("EPG Output:"))
            self.epg_path = QLineEdit("guide.xml")
            epg_layout.addWidget(self.epg_path)
            self.epg_browse = QPushButton("Browse")
            self.epg_browse.setIcon(qta.icon('fa5s.folder-open'))
            self.epg_browse.clicked.connect(lambda: self.browse_file("EPG"))
            epg_layout.addWidget(self.epg_browse)
            output_layout.addLayout(epg_layout)
            
            output_group.setLayout(output_layout)
            layout.addWidget(output_group)
            
            # Action buttons
            buttons_layout = QHBoxLayout()
            
            self.load_button = QPushButton("Load Channels")
            self.load_button.setIcon(qta.icon('fa5s.sync'))
            buttons_layout.addWidget(self.load_button)
            
            self.check_button = QPushButton("Check Selected")
            self.check_button.setIcon(qta.icon('fa5s.heartbeat'))
            self.check_button.setEnabled(False)
            buttons_layout.addWidget(self.check_button)
            
            self.generate_button = QPushButton("Generate Selected")
            self.generate_button.setIcon(qta.icon('fa5s.play-circle'))
            self.generate_button.setEnabled(False)
            buttons_layout.addWidget(self.generate_button)
            
            layout.addLayout(buttons_layout)
            
            # Log output
            self.log_output = QTextEdit()
            self.log_output.setReadOnly(True)
            self.log_output.setMaximumHeight(150)
            layout.addWidget(self.log_output)
            
            # Progress bar
            self.progress_bar = QProgressBar()
            layout.addWidget(self.progress_bar)
            
            # Connect progress signals
            self.progress_signal.connect(self.update_progress)
            self.check_progress.connect(lambda v: self.progress_bar.setValue(v))
            self.log_signal.connect(self.log_message)
            self.error_signal.connect(self.on_error)
            
        except Exception as e:
            logger.error(f"Error initializing UI: {str(e)}", exc_info=True)
            raise

    def load_channels(self):
        """Load channels from M3U files"""
        try:
            self.load_button.setEnabled(False)
            self.progress_bar.setValue(0)
            
            # Create worker thread
            self.worker = WorkerThread(self.load_m3u_files)
            self.worker.signals.progress.connect(self.update_progress)
            self.worker.signals.result.connect(self.handle_channels_loaded)
            self.worker.signals.error.connect(self.on_error)
            self.worker.start()
            
        except Exception as e:
            logger.error(f"Error starting channel load: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error starting channel load: {str(e)}")
            self.load_button.setEnabled(True)

    def handle_channels_loaded(self, channels):
        """Handle completion of channel loading"""
        try:
            self.all_channels = channels
            self.update_channels_table(channels)
            self.log_message(f"Loaded {len(channels)} channels")
            
            # Save channels after loading
            self.save_data()
            
            # Re-enable buttons
            self.load_button.setEnabled(True)
            self.check_button.setEnabled(True)
            self.generate_button.setEnabled(True)
            
            # Reset progress bar
            self.progress_bar.setValue(0)
            
        except Exception as e:
            logger.error(f"Error handling loaded channels: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error handling loaded channels: {str(e)}")

    def load_epg(self, epg_source):
        """Load EPG data from a source"""
        try:
            logger.info(f"Loading EPG from {epg_source['name']}")
            
            # Create session with timeout and retries
            epg_fetcher = requests.Session()
            retries = Retry(total=3, backoff_factor=0.5)
            epg_fetcher.mount('http://', HTTPAdapter(max_retries=retries))
            epg_fetcher.mount('https://', HTTPAdapter(max_retries=retries))
            
            try:
                response = epg_fetcher.get(epg_source['guide_url'], 
                                         stream=True, 
                                         timeout=10,
                                         verify=False)  # Skip SSL verification
                response.raise_for_status()
                
                # Handle gzipped content
                if response.headers.get('content-type') == 'application/x-gzip' or \
                   epg_source['guide_url'].endswith('.gz'):
                    xml_content = gzip.decompress(response.content).decode('utf-8')
                else:
                    xml_content = response.content.decode('utf-8')
                
                # Parse XML
                root = ET.fromstring(xml_content)
                
                # Process programs
                for program in root.findall('.//programme'):
                    channel = program.get('channel')
                    if channel:
                        if channel not in self.epg_data:
                            self.epg_data[channel] = []
                        self.epg_data[channel].append({
                            'start': program.get('start'),
                            'stop': program.get('stop'),
                            'title': program.find('title').text if program.find('title') is not None else '',
                            'desc': program.find('desc').text if program.find('desc') is not None else ''
                        })
                
                logger.info(f"Loaded {len(root.findall('.//programme'))} channel EPG data from {epg_source['name']}")
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error loading EPG source {epg_source['name']}: {str(e)}")
            except ET.ParseError as e:
                logger.error(f"Error parsing EPG XML from {epg_source['name']}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error loading EPG from {epg_source['name']}: {str(e)}")
            
        except Exception as e:
            logger.error(f"Error in load_epg for {epg_source['name']}: {str(e)}", exc_info=True)

    def load_saved_data(self):
        """Load saved channels and EPG data"""
        try:
            logger.info("Loading saved data")
            
            # Load channels with timeout
            start_time = time.time()
            channels_data = self.data_manager.load_channels()
            if channels_data:
                self.all_channels = []
                for channel_dict in channels_data:
                    channel = Channel(
                        name=channel_dict.get('name', ''),
                        url=channel_dict.get('url', ''),
                        group=channel_dict.get('group', ''),
                        tvg_id=channel_dict.get('tvg_id', ''),
                        tvg_name=channel_dict.get('tvg_name', ''),
                        tvg_logo=channel_dict.get('tvg_logo', ''),
                        has_epg=channel_dict.get('has_epg', False),
                        is_working=channel_dict.get('is_working', None)
                    )
                    self.all_channels.append(channel)
                logger.info(f"Loaded {len(self.all_channels)} channels in {time.time() - start_time:.2f} seconds")
                
                # Update table with loaded channels
                self.update_channels_table(self.all_channels)
            else:
                logger.info("No saved channels found")
            
            # Load EPG data with timeout
            start_time = time.time()
            epg_data = self.data_manager.load_epg_data()
            if epg_data:
                self.epg_data = epg_data
                logger.info(f"Loaded EPG data with {len(epg_data)} entries in {time.time() - start_time:.2f} seconds")
            else:
                logger.info("No saved EPG data found")
                
        except Exception as e:
            logger.error("Error loading saved data", exc_info=True)
            self.log_message(f"Error loading saved data: {str(e)}")

    def load_all_channels(self):
        """Load channels from all sources"""
        try:
            logger.info("Loading channels from all sources")
            self.progress_bar.setValue(0)
            self.load_button.setEnabled(False)
            self.generate_button.setEnabled(False)
            
            # Create worker thread for channel loading
            self.worker = WorkerThread(self.load_channels)
            self.worker.signals.progress.connect(self.update_progress)
            self.worker.signals.finished.connect(self.on_channels_loaded)
            self.worker.signals.error.connect(self.on_error)
            self.worker.start()

        except Exception as e:
            logger.error("Error starting load", exc_info=True)
            self.log_message(f"Error starting load: {str(e)}")
            self.load_button.setEnabled(True)

    def load_channels(self):
        """Load channels from various sources"""
        try:
            logger.info("Loading channels from various sources")
            self.progress_signal.emit("Loading channels...")
            generator = iptv_generator.PlaylistGenerator()
            channels = []
            
            # Load online sources
            for source in generator.PLAYLIST_SOURCES:
                try:
                    logger.info(f"Loading channels from {source['name']}")
                    response = generator.session.get(source['url'])
                    response.raise_for_status()
                    content = response.text
                    
                    if not content:
                        logger.warning(f"Warning: Empty content from {source['name']}")
                        continue
                        
                    # Parse M3U content
                    lines = content.split('\n')
                    i = 0
                    source_channels = 0
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith('#EXTINF:'):
                            # Parse channel info
                            try:
                                extinf_data = generator._parse_extinf(line)
                                if i + 1 < len(lines):
                                    url = lines[i + 1].strip()
                                    if url and not url.startswith('#'):
                                        channel = Channel(
                                            name=extinf_data.get('name', ''),
                                            url=url,
                                            group=extinf_data.get('group-title', ''),
                                            tvg_id=extinf_data.get('tvg-id', ''),
                                            tvg_name=extinf_data.get('tvg-name', ''),
                                            tvg_logo=extinf_data.get('tvg-logo', '')
                                        )
                                        channels.append(channel)
                                        source_channels += 1
                            except Exception as e:
                                logger.error(f"Error parsing channel in {source['name']}: {str(e)}", exc_info=True)
                            i += 2
                        else:
                            i += 1
                    
                    logger.info(f"Loaded {source_channels} channels from {source['name']}")
                            
                except Exception as e:
                    logger.error(f"Error loading source {source['name']}: {str(e)}", exc_info=True)
                    continue
                    
            # Load local playlists
            local_m3u_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_m3u')
            if os.path.exists(local_m3u_dir):
                for filename in os.listdir(local_m3u_dir):
                    if filename.endswith('.m3u') or filename.endswith('.m3u8'):
                        try:
                            logger.info(f"Loading local playlist: {filename}")
                            playlist_path = os.path.join(local_m3u_dir, filename)
                            
                            with open(playlist_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                
                            lines = content.split('\n')
                            i = 0
                            local_channels = 0
                            while i < len(lines):
                                line = lines[i].strip()
                                if line.startswith('#EXTINF:'):
                                    try:
                                        extinf_data = generator._parse_extinf(line)
                                        if i + 1 < len(lines):
                                            url = lines[i + 1].strip()
                                            if url and not url.startswith('#'):
                                                channel = Channel(
                                                    name=extinf_data.get('name', ''),
                                                    url=url,
                                                    group=extinf_data.get('group-title', ''),
                                                    tvg_id=extinf_data.get('tvg-id', ''),
                                                    tvg_name=extinf_data.get('tvg-name', ''),
                                                    tvg_logo=extinf_data.get('tvg-logo', '')
                                                )
                                                channels.append(channel)
                                                local_channels += 1
                                    except Exception as e:
                                        logger.error(f"Error parsing channel in {filename}: {str(e)}", exc_info=True)
                                    i += 2
                                else:
                                    i += 1
                                    
                            logger.info(f"Loaded {local_channels} channels from {filename}")
                                    
                        except Exception as e:
                            logger.error(f"Error loading local playlist {filename}: {str(e)}", exc_info=True)
                            continue

            if not channels:
                raise Exception("No channels were loaded from any source")

            self.all_channels = channels
            logger.info(f"Successfully loaded {len(channels)} channels total")
            
            # After channels are loaded, load EPG
            self.progress_signal.emit("Loading EPG data...")
            self.load_epg()
            
        except Exception as e:
            logger.error("Error loading channels", exc_info=True)
            self.error_signal.emit(str(e))

    def load_epg(self):
        """Load EPG data and update channel information"""
        try:
            logger.info("Loading EPG data")
            from iptv_generator import EPGFetcher
            import gzip
            import io
            
            epg_fetcher = EPGFetcher()
            epg_data = {}
            
            def decompress_content(content, url):
                if url.endswith('.gz'):
                    try:
                        return gzip.decompress(content).decode('utf-8')
                    except Exception as e:
                        logger.error(f"Failed to decompress content from {url}: {str(e)}", exc_info=True)
                        return content.decode('utf-8', errors='ignore')
                return content.decode('utf-8', errors='ignore')
            
            # Load EPG from each source
            for epg_source in EPGFetcher.EPG_SOURCES:
                try:
                    logger.info(f"Loading EPG from {epg_source['name']}")
                    response = epg_fetcher.session.get(epg_source['guide_url'], stream=True)
                    response.raise_for_status()
                    
                    # Get content and decompress if needed
                    content = decompress_content(response.content, epg_source['guide_url'])
                    
                    if not content:
                        continue
                    
                    # Parse EPG XML content
                    from xml.etree import ElementTree as ET
                    try:
                        root = ET.fromstring(content)
                        source_channels = 0
                        
                        # First pass: collect all channel IDs and their variations
                        for channel in root.findall('.//channel'):
                            channel_id = channel.get('id')
                            if channel_id:
                                epg_data[channel_id] = True
                                epg_data[channel_id.lower()] = True
                                epg_data[channel_id.replace(' ', '')] = True
                                
                                # Add common variations of channel IDs
                                if '.' in channel_id:
                                    base_id = channel_id.split('.')[0]
                                    epg_data[base_id] = True
                                    epg_data[base_id.lower()] = True
                                source_channels += 1
                        
                        # Second pass: collect programme channel IDs
                        for programme in root.findall('.//programme'):
                            channel = programme.get('channel')
                            if channel and channel not in epg_data:
                                epg_data[channel] = True
                                epg_data[channel.lower()] = True
                                epg_data[channel.replace(' ', '')] = True
                                source_channels += 1
                                
                        logger.info(f"Loaded {source_channels} channel EPG data from {epg_source['name']}")
                                
                    except ET.ParseError as e:
                        logger.error(f"Error parsing EPG XML from {epg_source['name']}: {str(e)}", exc_info=True)
                        continue
                            
                except Exception as e:
                    logger.error(f"Error loading EPG source {epg_source['name']}: {str(e)}", exc_info=True)
                    continue
            
            # Update channel EPG status
            self.epg_data = epg_data
            epg_count = 0
            
            # Helper function to check if a channel has EPG
            def has_epg_match(channel):
                # Direct match
                if channel.tvg_id in epg_data:
                    return True
                    
                # Case-insensitive match
                if channel.tvg_id.lower() in epg_data:
                    return True
                    
                # No-space match
                if channel.tvg_id.replace(' ', '') in epg_data:
                    return True
                    
                # Base ID match (without extension)
                if '.' in channel.tvg_id:
                    base_id = channel.tvg_id.split('.')[0]
                    if base_id in epg_data or base_id.lower() in epg_data:
                        return True
                        
                # Name-based match
                name_id = channel.name.lower().replace(' ', '')
                if name_id in epg_data:
                    return True
                    
                return False
            
            # Update EPG status for all channels
            for channel in self.all_channels:
                channel.has_epg = has_epg_match(channel)
                if channel.has_epg:
                    epg_count += 1
            
            logger.info(f"EPG data loaded for {epg_count} channels ({(epg_count/len(self.all_channels)*100):.1f}%)")
            return epg_data
            
        except Exception as e:
            logger.error("EPG loading error", exc_info=True)
            self.error_signal.emit(f"EPG loading error: {str(e)}")
            return {}

    def on_channels_loaded(self, channels):
        """Handle completion of channel loading"""
        try:
            self.all_channels = channels
            self.update_channels_table(channels)
            self.log_message(f"Loaded {len(channels)} channels")
            
            # Save channels after loading
            self.save_data()
            
        except Exception as e:
            logger.error(f"Error handling loaded channels: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error handling loaded channels: {str(e)}")

    def on_check_complete(self):
        """Handle completion of channel checking"""
        try:
            # Re-enable buttons
            self.check_button.setEnabled(True)
            self.generate_button.setEnabled(True)
            self.load_button.setEnabled(True)
            
            # Reset progress bar
            self.progress_bar.setValue(0)
            
            # Update status in table
            self.update_channels_table(self.all_channels)
            
            # Save updated channel statuses
            self.save_data()
            
            self.log_message("Channel check complete")
            
        except Exception as e:
            logger.error(f"Error completing channel check: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error completing channel check: {str(e)}")

    def save_data(self):
        """Save current channels and EPG data"""
        try:
            logger.info("Saving current data...")
            
            # Save channels
            if self.all_channels:
                channels_data = []
                for channel in self.all_channels:
                    channel_dict = {
                        'name': channel.name,
                        'url': channel.url,
                        'group': channel.group,
                        'tvg_id': channel.tvg_id,
                        'tvg_name': channel.tvg_name,
                        'tvg_logo': channel.tvg_logo,
                        'has_epg': channel.has_epg,
                        'is_working': channel.is_working
                    }
                    channels_data.append(channel_dict)
                self.data_manager.save_channels(channels_data)
                logger.info(f"Saved {len(channels_data)} channels")
            
            # Save EPG data
            if self.epg_data:
                self.data_manager.save_epg_data(self.epg_data)
                logger.info(f"Saved EPG data with {len(self.epg_data)} entries")
                
        except Exception as e:
            logger.error("Error saving data", exc_info=True)
            self.log_message(f"Error saving data: {str(e)}")

    def load_channels_from_m3u(self):
        """Load channels from M3U file"""
        try:
            logger.info("Loading channels from M3U file")
            channels = []
            
            # Read M3U file
            m3u_path = os.path.join('local_m3u', 'playlist.m3u')
            if not os.path.exists(m3u_path):
                logger.error(f"M3U file not found: {m3u_path}")
                return []
                
            with open(m3u_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse M3U content
            playlist = m3u8.loads(content)
            
            for item in playlist.segments:
                try:
                    # Extract channel info
                    channel = Channel(
                        name=item.title,
                        url=item.uri,
                        group=item.group_title if hasattr(item, 'group_title') else "",
                        tvg_id=item.tvg_id if hasattr(item, 'tvg_id') else "",
                        tvg_name=item.tvg_name if hasattr(item, 'tvg_name') else "",
                        tvg_logo=item.tvg_logo if hasattr(item, 'tvg_logo') else ""
                    )
                    channels.append(channel)
                    logger.debug(f"Loaded channel: {channel.name}")
                except Exception as e:
                    logger.error(f"Error parsing channel: {str(e)}", exc_info=True)
            
            logger.info(f"Successfully loaded {len(channels)} channels")
            
            # Save loaded channels
            self.all_channels = channels
            self.save_data()
            
            return channels
            
        except Exception as e:
            logger.error("Error loading channels from M3U", exc_info=True)
            return []

    def load_epg(self):
        """Load EPG data from XML files"""
        try:
            logger.info("Loading EPG data")
            from iptv_generator import EPGFetcher
            import gzip
            import io
            import xml.etree.ElementTree as ET
            
            epg_fetcher = EPGFetcher()
            epg_data = {}
            
            def decode_content(content, url):
                if url.endswith('.gz'):
                    try:
                        return gzip.decompress(content).decode('utf-8')
                    except Exception as e:
                        logger.error(f"Failed to decompress content from {url}: {str(e)}", exc_info=True)
                        return content.decode('utf-8', errors='ignore')
                return content.decode('utf-8', errors='ignore')
            
            # Process each EPG source
            for epg_source in EPGFetcher.EPG_SOURCES:
                try:
                    logger.info(f"Loading EPG from {epg_source['name']}")
                    response = epg_fetcher.session.get(epg_source['guide_url'], stream=True)
                    response.raise_for_status()
                    
                    content = response.content
                    xml_content = decode_content(content, epg_source['guide_url'])
                    
                    try:
                        source_channels = 0
                        root = ET.fromstring(xml_content)
                        
                        # Process each channel
                        for channel in root.findall('.//channel'):
                            channel_id = channel.get('id', '')
                            if channel_id:
                                epg_data[channel_id.replace(' ', '')] = True
                                source_channels += 1
                                
                        logger.info(f"Loaded {source_channels} channel EPG data from {epg_source['name']}")
                                
                    except ET.ParseError as e:
                        logger.error(f"Error parsing EPG XML from {epg_source['name']}: {str(e)}", exc_info=True)
                        continue
                            
                except Exception as e:
                    logger.error(f"Error loading EPG source {epg_source['name']}: {str(e)}", exc_info=True)
                    continue
            
            # Update channel EPG status
            epg_count = 0
            for channel in self.all_channels:
                channel.has_epg = bool(epg_data.get(channel.tvg_id.replace(' ', ''), False))
                if channel.has_epg:
                    epg_count += 1
            
            # Save EPG data
            self.epg_data = epg_data
            self.save_data()
            
            logger.info(f"EPG data loaded for {epg_count} channels ({(epg_count/len(self.all_channels)*100):.1f}%)")
            return epg_data
            
        except Exception as e:
            logger.error("EPG loading error", exc_info=True)
            self.error_signal.emit(f"EPG loading error: {str(e)}")
            return {}

    def generate(self):
        selected_channels = []
        for row in range(self.channels_table.rowCount()):
            if self.channels_table.item(row, 6).checkState() == Qt.Checked:
                selected_channels.append(self.all_channels[row])

        if not selected_channels:
            QMessageBox.warning(self, "Warning", "Please select at least one channel.")
            return

        self.generate_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        # Create worker thread
        self.worker = WorkerThread(
            self.generate_output,
            selected_channels,
            self.m3u_path.text(),
            self.epg_path.text()
        )
        self.worker.signals.finished.connect(self.generation_finished)
        self.worker.signals.error.connect(self.generation_error)
        self.worker.start()
        
    def generate_output(self, selected_channels, m3u_path, epg_path):
        try:
            # Generate M3U content
            content = "#EXTM3U\n"
            for channel in selected_channels:
                # Create EXTINF line
                extinf = f'#EXTINF:-1 tvg-id="{channel.tvg_id}" tvg-logo="{channel.tvg_logo}" group-title="{channel.group}",{channel.name}\n'
                content += extinf + channel.url + '\n'

            # Add EPG mapping
            generator = iptv_generator.PlaylistGenerator()
            content = generator.add_epg_mapping(content)
            
            # Save M3U file
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Generate EPG
            epg_fetcher = iptv_generator.EPGFetcher()
            epg_content = epg_fetcher.fetch_epg()
            
            # Save EPG file
            with open(epg_path, 'w', encoding='utf-8') as f:
                f.write(epg_content)

        except Exception as e:
            logger.error(f"Error generating output: {str(e)}")
            raise

    def setup_logging(self):
        # Remove all existing handlers
        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Create and add our Qt handler
        handler = QtHandler(self.log_signal)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def log_message(self, message):
        """Log message to both GUI and logger"""
        self.log_output.append(message)
        logger.info(message)

    def browse_file(self, file_type):
        file_filter = "M3U Files (*.m3u);;All Files (*.*)" if file_type == "M3U" else "XML Files (*.xml);;All Files (*.*)"
        filename, _ = QFileDialog.getSaveFileName(self, f"Save {file_type} File", "", file_filter)
        if filename:
            if file_type == "M3U":
                self.m3u_path.setText(filename)
            else:
                self.epg_path.setText(filename)

    def generation_finished(self):
        self.generate_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "Success", "Playlist and EPG generation completed successfully!")

    def generation_error(self, error_message):
        self.generate_button.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

    def on_selection_changed(self):
        """Handle table selection"""
        selected_count = sum(1 for row in range(self.channels_table.rowCount()) if self.channels_table.item(row, 6).checkState() == Qt.Checked)
        self.channel_count_label.setText(f"Channels: {selected_count}")
        
        # Enable/disable buttons based on selection
        has_selection = selected_count > 0
        self.generate_button.setEnabled(has_selection)
        self.check_button.setEnabled(has_selection)

    def update_channel_count(self):
        self.channel_count_label.setText(f"Channels: {self.channels_table.rowCount()}")

    def apply_filters(self):
        """Apply filters to the channels table"""
        if not self.all_channels:
            return

        try:
            search_text = self.search_input.text().lower()
            category = self.category_combo.currentText()
            country = self.country_edit.text().lower()
            official_only = self.official_only.isChecked()

            filtered_channels = []
            for channel in self.all_channels:
                # Check source filter
                if official_only and not channel.tvg_id.startswith('iptv-org'):
                    continue
                
                # Check search text
                if search_text and search_text not in channel.name.lower():
                    continue
                    
                # Check category
                if category != 'All' and category.lower() not in channel.group.lower():
                    continue
                    
                # Check country
                if country and not any(country in tag.lower() for tag in [channel.group, channel.name]):
                    continue
                    
                filtered_channels.append(channel)

            self.update_channels_table(filtered_channels)
            logger.info(f"Showing {len(filtered_channels)} channels after filtering")
            
        except Exception as e:
            logger.error(f"Error applying filters: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error applying filters: {str(e)}")

    def update_channels_table(self, channels):
        """Update the table with channel data"""
        try:
            # Disable sorting temporarily for better performance
            self.channels_table.setSortingEnabled(False)
            self.is_loading = True
            
            # Clear existing items and channel map
            self.channels_table.setRowCount(0)
            self.channel_map.clear()
            
            # Pre-allocate rows
            self.channels_table.setRowCount(len(channels))
            
            for row, channel in enumerate(channels):
                try:
                    # Store channel in map
                    self.channel_map[row] = channel
                    
                    # Create items
                    name_item = QTableWidgetItem(channel.name)
                    name_item.setData(Qt.UserRole, row)  # Store row index instead of channel
                    
                    category_item = QTableWidgetItem(channel.group)
                    country = channel.tvg_id.split('.')[0] if '.' in channel.tvg_id else ''
                    country_item = QTableWidgetItem(country)
                    source_item = QTableWidgetItem(channel.tvg_id)
                    
                    epg_item = QTableWidgetItem("Yes" if channel.has_epg else "No")
                    epg_item.setBackground(QColor(0, 255, 0) if channel.has_epg else QColor(255, 0, 0))
                    
                    status_text = "Unknown"
                    status_color = Qt.white
                    if channel.is_working is not None:
                        status_text = "Working" if channel.is_working else "Dead"
                        status_color = Qt.green if channel.is_working else Qt.red
                    status_item = QTableWidgetItem(status_text)
                    status_item.setBackground(status_color)
                    
                    # Create checkbox item
                    checkbox_item = QTableWidgetItem()
                    checkbox_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    checkbox_item.setCheckState(Qt.Checked if channel.tvg_id.startswith('iptv-org') else Qt.Unchecked)
                    
                    # Set items
                    self.channels_table.setItem(row, 0, name_item)
                    self.channels_table.setItem(row, 1, category_item)
                    self.channels_table.setItem(row, 2, country_item)
                    self.channels_table.setItem(row, 3, source_item)
                    self.channels_table.setItem(row, 4, epg_item)
                    self.channels_table.setItem(row, 5, status_item)
                    self.channels_table.setItem(row, 6, checkbox_item)
                    
                except Exception as e:
                    logger.error(f"Error adding channel {channel.name} to row {row}: {str(e)}")
                    continue
                    
            # Re-enable sorting and update
            self.channels_table.setSortingEnabled(True)
            self.update_channel_count()
            
            # Connect to sort indicator changed signal
            self.channels_table.horizontalHeader().sortIndicatorChanged.connect(self.on_sort_changed)
            
        except Exception as e:
            logger.error(f"Error updating channels table: {str(e)}")
            self.error_signal.emit(f"Error updating table: {str(e)}")
            
        finally:
            self.is_loading = False

    def get_channel_from_row(self, row):
        """Get channel object from table row"""
        try:
            # Get name item which contains the row index
            name_item = self.channels_table.item(row, 0)
            if not name_item:
                logger.debug(f"No name item found in row {row}")
                return None
            
            # Get original row index
            original_row = name_item.data(Qt.UserRole)
            if original_row is None:
                logger.warning(f"No row index stored in row {row}")
                return None
            
            # Get channel from map using original row
            channel = self.channel_map.get(original_row)
            if not channel:
                logger.warning(f"No channel found for row index {original_row}")
                return None
            
            if not isinstance(channel, Channel):
                logger.warning(f"Invalid channel data in row {row}")
                return None
            
            return channel
            
        except Exception as e:
            logger.error(f"Error getting channel from row {row}: {str(e)}")
            return None

    def on_sort_changed(self, logicalIndex, order):
        """Handle table sorting"""
        try:
            # Update channel map with new row positions
            new_channel_map = {}
            for row in range(self.channels_table.rowCount()):
                name_item = self.channels_table.item(row, 0)
                if name_item:
                    original_row = name_item.data(Qt.UserRole)
                    if original_row in self.channel_map:
                        new_channel_map[row] = self.channel_map[original_row]
                        name_item.setData(Qt.UserRole, row)
            
            # Update channel map
            self.channel_map = new_channel_map
            
        except Exception as e:
            logger.error(f"Error updating channel map after sort: {str(e)}")

    def select_all_visible(self):
        """Select all visible channels"""
        try:
            self.is_loading = True
            
            # Get visible rows
            visible_rows = []
            for row in range(self.channels_table.rowCount()):
                if not self.channels_table.isRowHidden(row):
                    visible_rows.append(row)
            
            # Update checkboxes for visible rows
            for row in visible_rows:
                checkbox_item = self.channels_table.item(row, self.checkbox_column)
                if checkbox_item:
                    checkbox_item.setCheckState(Qt.Checked)
            
            self.update_channel_count()
            
        except Exception as e:
            logger.error(f"Error selecting all visible channels: {str(e)}", exc_info=True)
        finally:
            self.is_loading = False

    def deselect_all(self):
        """Deselect all channels"""
        try:
            self.is_loading = True
            
            # Update all checkboxes
            for row in range(self.channels_table.rowCount()):
                checkbox_item = self.channels_table.item(row, self.checkbox_column)
                if checkbox_item:
                    checkbox_item.setCheckState(Qt.Unchecked)
            
            self.update_channel_count()
            
        except Exception as e:
            logger.error(f"Error deselecting all channels: {str(e)}", exc_info=True)
        finally:
            self.is_loading = False

    def update_channel_count(self):
        """Update the channel count label"""
        try:
            total_count = self.channels_table.rowCount()
            selected_count = 0
            
            for row in range(total_count):
                checkbox_item = self.channels_table.item(row, self.checkbox_column)
                if checkbox_item and checkbox_item.checkState() == Qt.Checked:
                    selected_count += 1
            
            self.channel_count_label.setText(f"Selected: {selected_count} / Total: {total_count}")
            
            # Enable/disable buttons based on selection
            has_selection = selected_count > 0
            self.check_button.setEnabled(has_selection)
            self.generate_button.setEnabled(has_selection)
            
        except Exception as e:
            logger.error(f"Error updating channel count: {str(e)}", exc_info=True)

    def on_cell_changed(self, row, column):
        """Handle cell changes in the table"""
        if self.is_loading:
            return
            
        if column == self.checkbox_column:
            try:
                checkbox_item = self.channels_table.item(row, column)
                if not checkbox_item:
                    return
                    
                channel_item = self.channels_table.item(row, 0)
                
                if channel_item:
                    channel_index = channel_item.data(Qt.UserRole)
                    if isinstance(channel_index, int):
                        channel = self.all_channels[channel_index]
                        state = "selected" if checkbox_item.checkState() == Qt.Checked else "unselected"
                        logger.info(f"Channel {channel.name} {state}")
                    else:
                        logger.warning(f"Warning: No channel index found in row {row}")
                else:
                    logger.warning(f"Warning: No channel item found in row {row}")
                    
            except Exception as e:
                logger.error(f"Error handling checkbox change: {str(e)}")

    def update_progress(self, message):
        """Update progress bar and log message"""
        self.log_signal.emit(message)
        if isinstance(message, int):
            # Handle progress value
            self.progress_bar.setValue(message)
        else:
            # Handle progress message
            self.log_message(message)

    def on_error(self, error_message):
        """Handle errors during loading"""
        self.load_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

    def check_selected_channels(self):
        """Check if selected channels are working"""
        try:
            selected_channels = []
            for row in range(self.channels_table.rowCount()):
                if self.channels_table.item(row, 0).checkState() == Qt.CheckState.Checked:
                    channel = self.get_channel_from_row(row)
                    if channel:
                        selected_channels.append(channel)
            
            if not selected_channels:
                QMessageBox.warning(self, 'Warning', 'Please select channels to check')
                return
            
            logger.info(f"Starting check of {len(selected_channels)} channels")
            self.progress_bar.setMaximum(len(selected_channels))
            self.progress_bar.setValue(0)
            
            # Disable buttons during check
            self.check_button.setEnabled(False)
            self.generate_button.setEnabled(False)
            self.load_button.setEnabled(False)
            
            # Create worker thread for checking channels
            self.worker = WorkerThread(self.check_channels, selected_channels)
            self.worker.signals.progress.connect(self.update_check_progress)
            self.worker.signals.finished.connect(lambda: self.on_check_complete(selected_channels))
            self.worker.signals.error.connect(self.on_error)
            self.worker.start()
            
        except Exception as e:
            logger.error("Error starting channel check", exc_info=True)
            self.log_message(f"Error starting channel check: {str(e)}")
            self.check_button.setEnabled(True)
            self.generate_button.setEnabled(True)
            self.load_button.setEnabled(True)

    def check_channels(self, channels):
        """Check if channels are working"""
        try:
            results = []
            total = len(channels)
            
            # Configure session with retry strategy
            session = requests.Session()
            retries = Retry(total=2, backoff_factor=1,
                          status_forcelist=[500, 502, 503, 504])
            session.mount('http://', HTTPAdapter(max_retries=retries))
            session.mount('https://', HTTPAdapter(max_retries=retries))
            
            for i, channel in enumerate(channels):
                try:
                    # Try to get stream headers with timeout
                    response = session.head(channel.url, 
                                         timeout=5,
                                         allow_redirects=True,
                                         verify=False)
                    
                    # Check if response is successful and contains video content
                    is_working = (response.status_code == 200 and
                                response.headers.get('content-type', '').startswith(('video/', 'application/')))
                    
                    channel.is_working = is_working
                    logger.info(f"Channel {channel.name}: {'Working' if is_working else 'Not working'}")
                    
                except Exception as e:
                    channel.is_working = False
                    logger.error(f"Error checking channel {channel.name}: {str(e)}")
                
                results.append(channel)
                # Emit progress update (channel, current count, total count)
                self.worker.signals.progress.emit((channel, i + 1, total))
                
            return results
            
        except Exception as e:
            logger.error("Error in check_channels", exc_info=True)
            raise

    def update_check_progress(self, progress_data):
        """Update progress bar and channel status during check"""
        try:
            channel, current, total = progress_data
            self.progress_bar.setValue(current)
            
            # Update channel status in table
            for row in range(self.channels_table.rowCount()):
                if self.channels_table.item(row, 1).text() == channel.name:
                    status_item = QTableWidgetItem()
                    if channel.is_working:
                        status_item.setIcon(QIcon.fromTheme('dialog-ok'))
                        status_item.setText('Working')
                    else:
                        status_item.setIcon(QIcon.fromTheme('dialog-error'))
                        status_item.setText('Not Working')
                    self.channels_table.setItem(row, 4, status_item)
                    break
                    
            # Update log
            status = 'Working' if channel.is_working else 'Not Working'
            self.log_message(f"Checked {current}/{total}: {channel.name} - {status}")
            
        except Exception as e:
            logger.error("Error updating check progress", exc_info=True)
            self.log_message(f"Error updating check progress: {str(e)}")

    def on_check_complete(self, checked_channels):
        """Handle completion of channel checking"""
        try:
            # Re-enable buttons
            self.check_button.setEnabled(True)
            self.generate_button.setEnabled(True)
            self.load_button.setEnabled(True)
            
            # Reset progress bar
            self.progress_bar.setValue(0)
            
            # Save updated channel statuses
            self.save_data()
            
            # Show summary
            working = sum(1 for ch in checked_channels if ch.is_working)
            total = len(checked_channels)
            QMessageBox.information(self, 'Check Complete', 
                                  f'Checked {total} channels\n'
                                  f'Working: {working}\n'
                                  f'Not Working: {total - working}')
            
            self.log_message("Channel check complete")
            
        except Exception as e:
            logger.error(f"Error completing channel check: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error completing channel check: {str(e)}")

    def get_channel_from_row(self, row):
        """Get channel object from table row"""
        try:
            name = self.channels_table.item(row, 1).text()
            url = self.channels_table.item(row, 3).text()
            group = self.channels_table.item(row, 2).text()
            
            # Find matching channel in all_channels
            for channel in self.all_channels:
                if channel.name == name and channel.url == url:
                    return channel
                    
            return None
            
        except Exception as e:
            logger.error(f"Error getting channel from row {row}: {str(e)}")
            return None

def main():
    app = QApplication(sys.argv)
    window = IPTVGeneratorGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

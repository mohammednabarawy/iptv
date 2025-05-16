import warnings
import urllib3
# Suppress only the InsecureRequestWarning from urllib3
warnings.filterwarnings('ignore', category=urllib3.exceptions.InsecureRequestWarning)

import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QPushButton, QLabel, QProgressBar,
                           QTextEdit, QFileDialog, QMessageBox, QTabWidget,
                           QListWidget, QListWidgetItem, QFrame, QTableWidget,
                           QTableWidgetItem, QHeaderView, QLineEdit, QComboBox, 
                           QCheckBox, QGroupBox)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QMetaObject, Q_ARG, pyqtSlot,
                         QObject, QRunnable, QThreadPool, QEventLoop)
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import ConfigManager
from PyQt5.QtCore import QThreadPool

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
    progress = pyqtSignal(tuple)  # Changed to tuple for (channel, current, total)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    result = pyqtSignal(object)

class ChannelCheckRunnable(QRunnable):
    """
    Runnable class for channel checking to work with QThreadPool
    """
    def __init__(self, fn, *args, **kwargs):
        """
        Initialize the runnable with a function and its arguments
        
        :param fn: Function to run
        :param args: Positional arguments
        :param kwargs: Keyword arguments
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
    
    @pyqtSlot()
    def run(self):
        """
        Run the function and handle signals
        """
        try:
            # Run the function
            result = self.fn(*self.args, **self.kwargs)
            
            # Emit result signal
            self.signals.result.emit(result)
            
            # Emit finished signal
            self.signals.finished.emit()
        
        except Exception as e:
            # Emit error signal if something goes wrong
            self.signals.error.emit(str(e))

class DataLoadWorker(QObject):
    """
    Worker class for asynchronous data loading from database
    """
    progress = pyqtSignal(int)  # Progress percentage (0-100)
    channels_loaded = pyqtSignal(object)  # Emits loaded channels
    epg_loaded = pyqtSignal(object)  # Emits loaded EPG data
    finished = pyqtSignal()  # Emitted when all loading is complete
    error = pyqtSignal(str)  # Emitted on error
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
    
    @pyqtSlot()
    def run(self):
        """
        Load data asynchronously
        """
        try:
            # Load channels (60% of progress)
            self.progress.emit(5)  # Starting
            channels_data = self.data_manager.load_channels()
            self.progress.emit(60)  # Channels loaded
            self.channels_loaded.emit(channels_data)
            
            # Load EPG data (40% of remaining progress)
            self.progress.emit(70)  # Starting EPG load
            epg_data = self.data_manager.load_epg_data()
            self.progress.emit(95)  # EPG loaded
            self.epg_loaded.emit(epg_data)
            
            # All done
            self.progress.emit(100)
            self.finished.emit()
            
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()


class FastChannelChecker(QObject):
    """
    Optimized channel checker using concurrent requests
    with improved performance and cancellation support
    """
    progress = pyqtSignal(tuple)  # Emits (current_progress, total_progress, channel)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, channels, max_workers=20, timeout=3):
        super().__init__()
        self.channels = channels
        self.max_workers = max_workers
        self.timeout = timeout
        self.is_stopped = False
        self.executor = None
    
    @pyqtSlot()
    def run(self):
        """
        Perform fast, concurrent channel checking
        Run this method in a separate thread
        """
        try:
            # Create a thread-safe session
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=self.max_workers, 
                pool_maxsize=self.max_workers,
                max_retries=Retry(
                    total=1,  # Minimal retries
                    backoff_factor=0.1,
                    status_forcelist=[500, 502, 503, 504]
                )
            )
            session.mount('http://', adapter)
            session.mount('https://', adapter)
            
            # Use concurrent futures for fast checking
            checked_channels = []
            
            # Use a context manager to ensure proper thread management
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                self.executor = executor  # Store reference for potential cancellation
                
                # Create futures for each channel
                future_to_channel = {
                    executor.submit(self._check_channel, session, channel): channel 
                    for channel in self.channels
                }
                
                # Process results as they complete
                for i, future in enumerate(concurrent.futures.as_completed(future_to_channel), 1):
                    # Check if stopping was requested
                    if self.is_stopped:
                        executor.shutdown(wait=False)
                        break
                    
                    channel = future_to_channel[future]
                    try:
                        checked_channel = future.result()
                        checked_channels.append(checked_channel)
                        
                        # Emit progress 
                        self.progress.emit((i, len(self.channels), checked_channel))
                    except Exception as e:
                        # Log individual channel check failures
                        print(f"Channel check failed: {channel.name} - {str(e)}")
            
            # Emit final results if not stopped
            if not self.is_stopped:
                self.finished.emit(checked_channels)
        
        except Exception as e:
            # Emit error if not stopped
            if not self.is_stopped:
                self.error.emit(f"Channel checking failed: {str(e)}")
        finally:
            # Ensure thread is terminated
            self.thread().quit()
    
    def _check_channel(self, session, channel):
        """
        Fast, lightweight channel checking method
        """
        try:
            # Use HEAD request for minimal overhead
            response = session.head(
                channel.url, 
                timeout=self.timeout, 
                allow_redirects=True,
                verify=False  # Consider making SSL verification configurable
            )
            
            # Determine channel status
            channel.is_working = (
                response.status_code == 200 and 
                any(t in response.headers.get('content-type', '').lower() 
                    for t in ['video/', 'application/x-mpegurl', 'application/vnd.apple.mpegurl'])
            )
            
            return channel
        
        except (requests.RequestException, Exception):
            # Mark as not working on any request error
            channel.is_working = False
            return channel
    
    def stop(self):
        """
        Signal to stop the checking process
        """
        self.is_stopped = True
        
        # Attempt to cancel any running futures
        if self.executor:
            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass

class IPTVGeneratorGUI(QMainWindow):
    progress_signal = pyqtSignal(object)  # For progress updates
    check_progress = pyqtSignal(int)      # For progress bar updates
    log_signal = pyqtSignal(str)          # For log messages
    error_signal = pyqtSignal(str)        # For error messages

    def __init__(self):
        super().__init__()
        
        try:
            # Initialize configuration BEFORE UI
            self.config = ConfigManager()
            
            # Initialize UI first
            self.init_ui()
            
            # Initialize data
            self.all_channels = []
            self.epg_data = {}
            self.channel_map = {}
            self.is_loading = False
            self.worker = None
            self.current_batch_index = 0
            
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
            
            # Apply initial theme from config
            if self.config.get('ui.theme') == 'dark':
                self.theme_toggle.setChecked(True)
                self.toggle_theme(Qt.Checked)
            
            # Load saved data
            self.load_saved_data()
            
        except Exception as e:
            logger.error(f"Error initializing main window: {str(e)}", exc_info=True)
            raise

    def init_ui(self):
        """Initialize the user interface"""
        try:
            logger.info("Initializing UI")
            
            # Set window properties
            self.setWindowTitle('IPTV Channel Generator')
            self.resize(1200, 800)
            
            # Create main layout
            main_widget = QWidget()
            main_layout = QVBoxLayout()
            main_widget.setLayout(main_layout)
            self.setCentralWidget(main_widget)
            
            # Create top layout for filters and buttons
            top_layout = QHBoxLayout()
            main_layout.addLayout(top_layout)
            
            # Filters group
            filter_group = QGroupBox("Filters")
            filter_layout = QHBoxLayout()
            
            # Search input
            search_label = QLabel("Search:")
            self.search_input = QLineEdit()
            filter_layout.addWidget(search_label)
            filter_layout.addWidget(self.search_input)
            
            # Category combo
            category_label = QLabel("Category:")
            self.category_combo = QComboBox()
            filter_layout.addWidget(category_label)
            filter_layout.addWidget(self.category_combo)
            
            # Country input
            country_label = QLabel("Country:")
            self.country_edit = QLineEdit()
            filter_layout.addWidget(country_label)
            filter_layout.addWidget(self.country_edit)
            
            # Official channels only
            self.official_only = QCheckBox("Official Only")
            self.official_only.setChecked(False)  # Default to show all channels
            filter_layout.addWidget(self.official_only)
            
            # Theme toggle
            self.theme_toggle = QCheckBox("Dark Mode")
            self.theme_toggle.stateChanged.connect(self.toggle_theme)
            filter_layout.addWidget(self.theme_toggle)
            
            filter_group.setLayout(filter_layout)
            top_layout.addWidget(filter_group)
            
            # Create channels table
            self.channels_table = QTableWidget()
            self.channels_table.setColumnCount(6)
            self.channels_table.setHorizontalHeaderLabels([
                "Select", "Name", "Group", "URL", "Status", "EPG"
            ])
            
            # Set column resize modes
            self.channels_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.channels_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.channels_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.channels_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.channels_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            self.channels_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            
            # Enable sorting
            self.channels_table.setSortingEnabled(True)
            
            # Add selection counter
            self.selected_count_label = QLabel("Selected: 0")
            
            # Connect selection signal
            self.channels_table.itemChanged.connect(self.on_selection_changed)
            
            main_layout.addWidget(self.channels_table)
            
            # Selection buttons and count
            selection_layout = QHBoxLayout()
            
            count_label = QLabel()
            count_label.setPixmap(qta.icon('fa5s.list').pixmap(16, 16))
            selection_layout.addWidget(count_label)
            selection_layout.addWidget(self.selected_count_label)
            
            selection_layout.addStretch()
            
            self.select_all_button = QPushButton("Select All")
            self.select_all_button.setIcon(qta.icon('fa5s.check-square'))
            selection_layout.addWidget(self.select_all_button)
            
            self.deselect_all_button = QPushButton("Deselect All")
            self.deselect_all_button.setIcon(qta.icon('fa5s.square'))
            selection_layout.addWidget(self.deselect_all_button)
            
            main_layout.addLayout(selection_layout)
            
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
            main_layout.addWidget(output_group)
            
            # Action buttons
            buttons_layout = QHBoxLayout()
            
            self.load_button = QPushButton("Load Channels")
            self.load_button.setIcon(qta.icon('fa5s.sync'))
            buttons_layout.addWidget(self.load_button)
            
            self.check_button = QPushButton("Check Selected")
            self.check_button.setIcon(qta.icon('fa5s.heartbeat'))
            self.check_button.setEnabled(False)
            buttons_layout.addWidget(self.check_button)
            
            self.stop_button = QPushButton("Stop Checking")
            self.stop_button.setIcon(qta.icon('fa5s.stop-circle'))
            self.stop_button.setEnabled(False)
            self.stop_button.clicked.connect(self.stop_checking)
            buttons_layout.addWidget(self.stop_button)
            
            self.generate_button = QPushButton("Generate Selected")
            self.generate_button.setIcon(qta.icon('fa5s.play-circle'))
            self.generate_button.setEnabled(False)
            buttons_layout.addWidget(self.generate_button)
            
            main_layout.addLayout(buttons_layout)
            
            # Log output
            self.log_output = QTextEdit()
            self.log_output.setReadOnly(True)
            self.log_output.setMaximumHeight(150)
            main_layout.addWidget(self.log_output)
            
            # Progress bar
            self.progress_bar = QProgressBar()
            main_layout.addWidget(self.progress_bar)
            
            # Connect progress signals
            self.progress_signal.connect(self.update_progress)
            self.check_progress.connect(lambda v: self.progress_bar.setValue(v))
            self.log_signal.connect(self.log_message)
            self.error_signal.connect(self.on_error)
            
        except Exception as e:
            logger.error(f"Error initializing UI: {str(e)}", exc_info=True)
            raise

    def toggle_theme(self, state):
        """Toggle between light and dark themes"""
        try:
            if state == Qt.Checked:
                # Dark theme
                dark_palette = QPalette()
                dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
                dark_palette.setColor(QPalette.WindowText, Qt.white)
                dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
                dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
                dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
                dark_palette.setColor(QPalette.ToolTipText, Qt.white)
                dark_palette.setColor(QPalette.Text, Qt.white)
                dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
                dark_palette.setColor(QPalette.ButtonText, Qt.white)
                dark_palette.setColor(QPalette.BrightText, Qt.red)
                dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
                dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
                dark_palette.setColor(QPalette.HighlightedText, Qt.black)
                
                QApplication.setPalette(dark_palette)
                QApplication.setStyle("Fusion")
            else:
                # Light theme
                QApplication.setPalette(QApplication.style().standardPalette())
                QApplication.setStyle("Windows")
        except Exception as e:
            logger.error(f"Error toggling theme: {e}", exc_info=True)

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
                def decode_content(content, url):
                    """Decode content based on the URL and content type"""
                    import gzip
                    from io import BytesIO
                    
                    try:
                        # Check if the content is gzipped
                        if url.endswith('.gz'):
                            try:
                                # Use BytesIO to handle the gzipped content in memory
                                with BytesIO(content) as buf:
                                    with gzip.GzipFile(fileobj=buf) as gz:
                                        content = gz.read()
                            except gzip.BadGzipFile:
                                logger.warning(f"Content from {url} appears to be not properly gzipped, trying direct decode")
                        
                        # Try UTF-8 decoding first
                        return content.decode('utf-8', errors='ignore')
                        
                    except Exception as e:
                        logger.error(f"Error decoding content from {url}: {str(e)}")
                        raise
                
                content = response.content
                xml_content = decode_content(content, epg_source['guide_url'])
                
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
        """Load saved channels and EPG data with optimized async loading"""
        try:
            logger.info("Loading saved data")
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            
            # Create a worker thread for loading data
            # This moves the loading process off the main UI thread
            self.load_data_thread = QThread()
            self.load_data_worker = DataLoadWorker(self.data_manager)
            self.load_data_worker.moveToThread(self.load_data_thread)
            
            # Connect signals
            self.load_data_thread.started.connect(self.load_data_worker.run)
            self.load_data_worker.channels_loaded.connect(self.on_channels_loaded_from_db)
            self.load_data_worker.epg_loaded.connect(self.on_epg_loaded_from_db)
            self.load_data_worker.progress.connect(self.update_load_progress)
            self.load_data_worker.finished.connect(self.load_data_thread.quit)
            self.load_data_worker.finished.connect(self.load_data_worker.deleteLater)
            self.load_data_thread.finished.connect(self.load_data_thread.deleteLater)
            
            # Start the worker thread
            self.load_data_thread.start()
            
        except Exception as e:
            logger.error("Error loading saved data", exc_info=True)
            self.log_message(f"Error loading saved data: {str(e)}")
            self.progress_bar.setValue(0)
    
    def update_load_progress(self, progress):
        """Update progress bar during data loading"""
        self.progress_bar.setValue(progress)
    
    def on_channels_loaded_from_db(self, channels_data):
        """Handle channels loaded from database"""
        try:
            if channels_data:
                # Process channels in batches to avoid UI freezing
                self.all_channels = []
                batch_size = 10000
                
                # Calculate total batches for progress updates
                total_batches = (len(channels_data) + batch_size - 1) // batch_size
                
                for batch_index in range(total_batches):
                    # Get current batch
                    start_idx = batch_index * batch_size
                    end_idx = min(start_idx + batch_size, len(channels_data))
                    batch = channels_data[start_idx:end_idx]
                    
                    # Process batch
                    batch_channels = [Channel(
                        name=ch.get('name', ''),
                        url=ch.get('url', ''),
                        group=ch.get('group', ''),
                        tvg_id=ch.get('tvg_id', ''),
                        tvg_name=ch.get('tvg_name', ''),
                        tvg_logo=ch.get('tvg_logo', ''),
                        has_epg=ch.get('has_epg', False),
                        is_working=ch.get('is_working', None)
                    ) for ch in batch]
                    
                    self.all_channels.extend(batch_channels)
                    
                    # Allow UI to process events between batches
                    QApplication.processEvents()
                
                logger.info(f"Processed {len(self.all_channels)} channels into objects")
                
                # Update table with loaded channels
                self.update_channels_table(self.all_channels)
            else:
                logger.info("No saved channels found")
                
        except Exception as e:
            logger.error(f"Error processing loaded channels: {str(e)}", exc_info=True)
    
    def on_epg_loaded_from_db(self, epg_data):
        """Handle EPG data loaded from database"""
        try:
            if epg_data:
                self.epg_data = epg_data
                logger.info(f"Loaded EPG data with {len(epg_data)} entries")
            else:
                logger.info("No saved EPG data found")
                
        except Exception as e:
            logger.error(f"Error processing loaded EPG data: {str(e)}", exc_info=True)

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
                            
                            with open(playlist_path, 'r', encoding='utf-8') as f:
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
                                    logger.error(f"Error parsing channel in {filename}: {str(e)}", exc_info=True)
                                    
                            logger.info(f"Loaded {len(playlist.segments)} channels from {filename}")
                                    
                        except Exception as e:
                            logger.error(f"Error loading local playlist {filename}: {str(e)}", exc_info=True)
                            continue

            if not channels:
                raise Exception("No channels were loaded from any source")

            self.all_channels = channels
            logger.info(f"Successfully loaded {len(channels)} channels total")
            
            # After channels are loaded, load EPG
            self.progress_signal.emit("Loading EPG data...")
            from epg_fetcher_optimized import EPGFetcher
            self.load_epg()
            
        except Exception as e:
            logger.error("Error loading channels", exc_info=True)
            self.error_signal.emit(str(e))

    def load_epg(self):
        """Load EPG data from various sources"""
        try:
            logger.info("Loading EPG data...")
            epg_fetcher = EPGFetcher(max_workers=10)
            
            # Fetch EPG data with optimized fetcher
            self.epg_data = epg_fetcher.fetch_epg()
            
            # Update channel EPG status
            epg_count = 0
            for channel in self.all_channels:
                channel_id = channel.tvg_id.replace(' ', '')
                channel.has_epg = (
                    channel_id in self.epg_data or
                    channel_id.lower() in self.epg_data or
                    (channel.name.lower().replace(' ', '') in self.epg_data)
                )
                if channel.has_epg:
                    epg_count += 1
            
            logger.info(f"EPG data loaded for {epg_count} channels ({(epg_count/len(self.all_channels)*100):.1f}%)")
            return self.epg_data
            
        except Exception as e:
            logger.error(f"Error in load_epg: {str(e)}")
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

    def on_check_complete(self, checked_channels):
        """
        Handle completion of channel checking
        """
        try:
            # Use QTimer to ensure UI updates happen on main thread
            from PyQt5.QtCore import QTimer
            
            def update_ui():
                try:
                    # Update UI and log results
                    self.log_message(f"Checked {len(checked_channels)} channels")
                    
                    # Update channel status in the table
                    for channel in checked_channels:
                        for row in range(self.channels_table.rowCount()):
                            table_channel = self.get_channel_from_row(row)
                            if table_channel and table_channel.url == channel.url:
                                # Update working status
                                status_item = self.channels_table.item(row, 4)  # Status column is index 4
                                if status_item:
                                    status_item.setText("Working" if channel.is_working else "Not Working")
                                    status_item.setForeground(Qt.green if channel.is_working else Qt.red)
                                break
                    
                    # Reset UI state
                    self.progress_bar.setValue(self.progress_bar.maximum())
                    self.stop_button.setEnabled(False)
                    
                    # Re-enable buttons
                    self.check_button.setEnabled(True)
                    self.generate_button.setEnabled(True)
                    self.load_button.setEnabled(True)
                    
                    # Save results
                    self.save_data()
                    
                    self.log_message("Channel check complete")
                
                except Exception as e:
                    logger.error(f"Error updating UI after channel check: {str(e)}", exc_info=True)
            
            # Ensure UI updates happen on main thread
            QTimer.singleShot(0, update_ui)
            
        except Exception as e:
            logger.error(f"Error in on_check_complete: {str(e)}", exc_info=True)
            self.log_message(f"Error processing channel check results: {str(e)}")

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
                """Decode content based on the URL and content type"""
                import gzip
                from io import BytesIO
                
                try:
                    # Check if the content is gzipped
                    if url.endswith('.gz'):
                        try:
                            # Use BytesIO to handle the gzipped content in memory
                            with BytesIO(content) as buf:
                                with gzip.GzipFile(fileobj=buf) as gz:
                                    content = gz.read()
                        except gzip.BadGzipFile:
                            logger.warning(f"Content from {url} appears to be not properly gzipped, trying direct decode")
                    
                    # Try UTF-8 decoding first
                    return content.decode('utf-8', errors='ignore')
                    
                except Exception as e:
                    logger.error(f"Error decoding content from {url}: {str(e)}")
                    raise
            
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

    def update_channels_table(self, channels):
        """Update the channels table with the given channels"""
        try:
            # Temporarily block signals to prevent multiple updates
            self.channels_table.blockSignals(True)
            
            # Clear existing items
            self.channels_table.setRowCount(0)
            
            # Clear channel map
            self.channel_map.clear()
            
            # Add channels to table
            for i, channel in enumerate(channels):
                row = self.channels_table.rowCount()
                self.channels_table.insertRow(row)
                
                # Store channel mapping
                self.channel_map[row] = channel
                
                # Select checkbox
                checkbox = QTableWidgetItem()
                checkbox.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                checkbox.setCheckState(Qt.Unchecked)
                self.channels_table.setItem(row, 0, checkbox)
                
                # Channel name
                name_item = QTableWidgetItem(channel.name)
                self.channels_table.setItem(row, 1, name_item)
                
                # Channel group
                group_item = QTableWidgetItem(channel.group)
                self.channels_table.setItem(row, 2, group_item)
                
                # Channel URL
                url_item = QTableWidgetItem(channel.url)
                self.channels_table.setItem(row, 3, url_item)
                
                # Working status
                status_item = QTableWidgetItem()
                if channel.is_working is not None:
                    status_text = "Working" if channel.is_working else "Not Working"
                    status_item.setText(status_text)
                    status_item.setForeground(Qt.green if channel.is_working else Qt.red)
                self.channels_table.setItem(row, 4, status_item)
                
                # EPG status
                epg_item = QTableWidgetItem("Yes" if channel.has_epg else "No")
                epg_item.setForeground(Qt.green if channel.has_epg else Qt.gray)
                self.channels_table.setItem(row, 5, epg_item)
            
            # Re-enable signals
            self.channels_table.blockSignals(False)
            
            # Update counts
            self.update_channel_count()
            
        except Exception as e:
            logger.error(f"Error updating channels table: {str(e)}", exc_info=True)

    def on_selection_changed(self, item):
        """Handle changes in channel selection"""
        if item and item.column() == 0:  # Check if it's the checkbox column
            self.update_selected_count()

    def update_selected_count(self):
        """Update selected count and button states"""
        try:
            # Use list comprehension for better performance
            selected_count = sum(
                1 for row in range(self.channels_table.rowCount())
                if self.channels_table.item(row, 0).checkState() == Qt.Checked
            )
            
            # Update status label
            self.selected_count_label.setText(f"Selected: {selected_count}")
            
            # Update button states
            has_selection = selected_count > 0
            self.check_button.setEnabled(has_selection)
            self.generate_button.setEnabled(has_selection)
            
            logger.debug(f"Selection changed: {selected_count} channels selected")
            
        except Exception as e:
            logger.error(f"Error updating selection count: {str(e)}", exc_info=True)

    def select_all_visible(self):
        """Select all visible channels"""
        try:
            # Disconnect signal temporarily to prevent multiple updates
            self.channels_table.itemChanged.disconnect(self.on_selection_changed)
            
            # Batch select all visible channels
            for row in range(self.channels_table.rowCount()):
                if not self.channels_table.isRowHidden(row):
                    self.channels_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
            
            # Reconnect signal and update once
            self.channels_table.itemChanged.connect(self.on_selection_changed)
            self.update_selected_count()
            
        except Exception as e:
            logger.error(f"Error selecting all channels: {str(e)}", exc_info=True)
            # Ensure signal is reconnected even if there's an error
            self.channels_table.itemChanged.connect(self.on_selection_changed)

    def deselect_all(self):
        """Deselect all channels"""
        try:
            # Disconnect signal temporarily to prevent multiple updates
            self.channels_table.itemChanged.disconnect(self.on_selection_changed)
            
            # Batch deselect all channels
            for row in range(self.channels_table.rowCount()):
                self.channels_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            
            # Reconnect signal and update once
            self.channels_table.itemChanged.connect(self.on_selection_changed)
            self.update_selected_count()
            
        except Exception as e:
            logger.error(f"Error deselecting all channels: {str(e)}", exc_info=True)
            # Ensure signal is reconnected even if there's an error
            self.channels_table.itemChanged.connect(self.on_selection_changed)

    def generate(self):
        """Generate output files for selected channels"""
        try:
            selected_channels = []
            for row in range(self.channels_table.rowCount()):
                if self.channels_table.item(row, 0).checkState() == Qt.Checked:
                    channel = self.get_channel_from_row(row)
                    if channel:
                        selected_channels.append(channel)

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
            
        except Exception as e:
            logger.error(f"Error starting generation: {str(e)}", exc_info=True)
            self.generate_button.setEnabled(True)

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
        selected_count = sum(1 for row in range(self.channels_table.rowCount()) if self.channels_table.item(row, 0).checkState() == Qt.Checked)
        self.selected_count_label.setText(f"Selected: {selected_count}")
        
        # Enable/disable buttons based on selection
        has_selection = selected_count > 0
        self.generate_button.setEnabled(has_selection)
        self.check_button.setEnabled(has_selection)

    def update_channel_count(self):
        self.selected_count_label.setText(f"Channels: {self.channels_table.rowCount()}")

    def apply_filters(self):
        """Apply filters to the channels table"""
        if not self.all_channels:
            return

        try:
            search_text = self.search_input.text().lower().strip()
            category = self.category_combo.currentText()
            country = self.country_edit.text().lower().strip()
            official_only = self.official_only.isChecked()

            filtered_channels = []
            for channel in self.all_channels:
                # Skip empty channels
                if not channel.name or not channel.url:
                    continue
                    
                # Check source filter (only if checked)
                if official_only and not any(src in channel.tvg_id.lower() for src in ['iptv-org', 'github']):
                    continue
                
                # Check search text (only if provided)
                if search_text and not any(search_text in field.lower() for field in [channel.name, channel.group, channel.tvg_name] if field):
                    continue
                    
                # Check category (only if not All)
                if category != 'All' and not any(category.lower() in field.lower() for field in [channel.group, channel.name] if field):
                    continue
                    
                # Check country (only if provided)
                if country and not any(country in field.lower() for field in [channel.group, channel.name, channel.tvg_name] if field):
                    continue
                    
                filtered_channels.append(channel)

            self.update_channels_table(filtered_channels)
            self.update_channel_count()
            logger.info(f"Showing {len(filtered_channels)} channels after filtering")
            
        except Exception as e:
            logger.error(f"Error applying filters: {str(e)}", exc_info=True)
            self.error_signal.emit(f"Error applying filters: {str(e)}")

    def get_channel_from_row(self, row):
        """Get channel object from table row"""
        try:
            # Get channel directly from the mapping
            channel = self.channel_map.get(row)
            if not channel:
                logger.debug(f"No channel found in map for row {row}")
                return None
                
            if not isinstance(channel, Channel):
                logger.warning(f"Invalid channel data in row {row}")
                return None
            
            return channel
            
        except Exception as e:
            logger.error(f"Error getting channel from row {row}: {str(e)}")
            return None

    def update_progress(self, progress_data):
        """
        Update progress bar and log progress
        
        :param progress_data: Tuple of (current_progress, total_progress, channel)
                             or a string message
        """
        try:
            # Check if input is a tuple (from channel checking)
            if isinstance(progress_data, tuple) and len(progress_data) == 3:
                current, total, channel = progress_data
                
                # Update progress bar
                self.progress_bar.setValue(current)
                
                # Log progress
                progress_message = f"Checking channel {current}/{total}: {channel.name}"
                self.log_signal.emit(progress_message)
                
                # Optionally update channel status in table
                for row in range(self.channels_table.rowCount()):
                    table_channel = self.get_channel_from_row(row)
                    if table_channel and table_channel.url == channel.url:
                        status_item = self.channels_table.item(row, 3)  # Status column is index 3
                        if status_item:
                            status_item.setText("Checking...")
                        break
            
            # If input is a string message
            elif isinstance(progress_data, str):
                self.log_signal.emit(progress_data)
                
            # Update progress bar if possible
            if hasattr(self, 'progress_bar'):
                self.progress_bar.repaint()
        
        except Exception as e:
            logger.error(f"Error in update_progress: {str(e)}", exc_info=True)
            # Fallback logging
            print(f"Progress update error: {str(e)}")

    def on_error(self, error_message):
        """Handle errors during loading"""
        self.load_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

    def check_selected_channels(self):
        """
        Check selected channels with improved performance and responsiveness
        Process channels in batches to prevent UI freezing
        """
        # Create or reset thread pool
        if not hasattr(self, 'thread_pool'):
            self.thread_pool = QThreadPool()
        
        # Set max thread count
        self.thread_pool.setMaxThreadCount(max(4, os.cpu_count() * 2))
        
        # Get selected channels
        selected_channels = [
            self.get_channel_from_row(row) 
            for row in range(self.channels_table.rowCount())
            if self.channels_table.item(row, 0).checkState() == Qt.Checked
        ]
        
        if not selected_channels:
            QMessageBox.warning(self, "No Channels", "Please select channels to check.")
            return
        
        # Determine if all channels are selected
        all_channels_selected = len(selected_channels) == self.channels_table.rowCount()
        
        # If all channels are selected, process in batches of 10
        if all_channels_selected:
            # Split channels into batches of 10
            channel_batches = [
                selected_channels[i:i+10] 
                for i in range(0, len(selected_channels), 10)
            ]
        else:
            # If not all channels, process all selected channels in one batch
            channel_batches = [selected_channels]
        
        # Reset progress
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(selected_channels))
        
        # Store batches for processing
        self.channel_batches = channel_batches
        self.current_batch_index = 0
        
        # Start batch processing
        self.process_next_channel_batch()
        
        # Stop button functionality
        self.stop_button.clicked.connect(self.stop_checking)
        self.stop_button.setEnabled(True)
        
        # Disable other buttons during checking
        self.check_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.load_button.setEnabled(False)
        
        self.log_message(f"Starting channel check for {len(selected_channels)} channels in batches")
    
    def process_next_channel_batch(self):
        """
        Process the next batch of channels
        """
        try:
            # Ensure batch index is initialized
            if not hasattr(self, 'current_batch_index'):
                self.current_batch_index = 0
                
            # Ensure channel_batches exists
            if not hasattr(self, 'channel_batches'):
                self.log_message("No channel batches to process")
                self.finalize_channel_check()
                return
                
            # Check if there are more batches to process
            if self.current_batch_index < len(self.channel_batches):
                # Get current batch
                current_batch = self.channel_batches[self.current_batch_index]
                
                # Create a runnable for channel checking
                channel_check_runnable = ChannelCheckRunnable(
                    self.perform_channel_check, 
                    current_batch
                )
                
                # Connect signals
                channel_check_runnable.signals.result.connect(self.on_batch_check_complete)
                channel_check_runnable.signals.error.connect(self.on_worker_error)
                
                # Start checking this batch
                self.thread_pool.start(channel_check_runnable)
                
                # Log batch processing
                self.log_message(f"Processing batch {self.current_batch_index + 1}/{len(self.channel_batches)}")
            else:
                # All batches processed
                self.finalize_channel_check()
        
        except Exception as e:
            logger.error(f"Error processing channel batch: {str(e)}", exc_info=True)
            self.finalize_channel_check()
    
    def on_batch_check_complete(self, checked_channels):
        """
        Handle completion of a batch of channel checking
        """
        try:
            # Update UI with this batch's results
            for channel in checked_channels:
                for row in range(self.channels_table.rowCount()):
                    table_channel = self.get_channel_from_row(row)
                    if table_channel and table_channel.url == channel.url:
                        # Update working status in the correct column
                        status_item = self.channels_table.item(row, 3)  # Status column is index 3
                        if status_item:
                            status_text = "Working" if channel.is_working else "Not Working"
                            status_item.setText(status_text)
                            status_item.setForeground(Qt.green if channel.is_working else Qt.red)
                        
                        # Optional: Update the channel object in the table
                        table_channel.is_working = channel.is_working
                        break
            
            # Move to next batch - ensure attribute exists
            if not hasattr(self, 'current_batch_index'):
                self.current_batch_index = 0
            
            self.current_batch_index += 1
            
            # Update progress bar
            current_progress = min(
                self.current_batch_index * 10, 
                self.progress_bar.maximum()
            )
            self.progress_bar.setValue(current_progress)
            
            # Process next batch
            self.process_next_channel_batch()
        
        except Exception as e:
            logger.error(f"Error in batch check complete: {str(e)}", exc_info=True)
            self.finalize_channel_check()
    
    def finalize_channel_check(self):
        """
        Finalize the channel checking process
        """
        try:
            # Reset UI state
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.stop_button.setEnabled(False)
            
            # Re-enable buttons
            self.check_button.setEnabled(True)
            self.generate_button.setEnabled(True)
            self.load_button.setEnabled(True)
            
            # Save results
            self.save_data()
            
            self.log_message("Channel check complete")
            
            # Clear batch-related attributes
            if hasattr(self, 'channel_batches'):
                del self.channel_batches
            if hasattr(self, 'current_batch_index'):
                del self.current_batch_index
        
        except Exception as e:
            logger.error(f"Error finalizing channel check: {str(e)}", exc_info=True)
            self.log_message(f"Error finalizing channel check: {str(e)}")

    def stop_checking(self):
        """Stop the ongoing channel checking process"""
        try:
            # Stop the channel checking thread if it exists
            if hasattr(self, 'channel_checker'):
                self.channel_checker.stop()
            
            # Stop any ongoing batch processing
            if hasattr(self, 'channel_batches'):
                # Clear remaining batches
                self.channel_batches = self.channel_batches[:self.current_batch_index + 1]
            
            # Stop thread pool
            if hasattr(self, 'thread_pool'):
                try:
                    self.thread_pool.clear()
                    self.thread_pool.waitForDone()
                except Exception as pool_error:
                    logger.error(f"Error stopping thread pool: {str(pool_error)}", exc_info=True)
            
            # Finalize the channel check
            self.finalize_channel_check()
            
            # Log the stopping of channel check
            self.log_message("Channel checking stopped by user.")
        
        except Exception as e:
            logger.error(f"Error stopping channel check: {str(e)}", exc_info=True)
            self.log_message(f"Error stopping channel check: {str(e)}")
            
            # Ensure UI is reset even if stopping fails
            self.finalize_channel_check()

    def on_worker_error(self, error_message):
        """Handle worker thread errors"""
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

    def perform_channel_check(self, selected_channels):
        """
        Perform the actual channel checking
        
        :param selected_channels: List of channels to check
        :return: List of checked channels
        """
        # Create a channel checker
        channel_checker = FastChannelChecker(selected_channels)
        
        # Create an event loop to run the channel checker
        loop = QEventLoop()
        checked_channels = []
        
        def on_finished(channels):
            nonlocal checked_channels
            checked_channels = channels
            loop.quit()
        
        def on_error(error):
            logger.error(f"Channel check error: {error}")
            loop.quit()
        
        # Connect signals
        channel_checker.finished.connect(on_finished)
        channel_checker.error.connect(on_error)
        channel_checker.progress.connect(self.update_progress)
        
        # Run the channel checker
        channel_checker.run()
        
        # Start the event loop
        loop.exec_()
        
        return checked_channels

def main():
    app = QApplication(sys.argv)
    window = IPTVGeneratorGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

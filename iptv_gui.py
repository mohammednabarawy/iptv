import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QLineEdit, QComboBox, 
                           QPushButton, QCheckBox, QGroupBox, QProgressBar,
                           QTextEdit, QFileDialog, QMessageBox, QTabWidget,
                           QListWidget, QListWidgetItem, QFrame, QTableWidget,
                           QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon
import qtawesome as qta
import iptv_generator
import logging
import os

class Channel:
    def __init__(self, name, group, url, tvg_id="", tvg_logo="", source=""):
        self.name = name
        self.group = group
        self.url = url
        self.tvg_id = tvg_id
        self.tvg_logo = tvg_logo
        self.source = source
        self.is_official = source.startswith('iptv-org')
        self.has_epg = False  # Will be updated after EPG loading

class WorkerThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    epg_loaded = pyqtSignal(dict)  # New signal for EPG data

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            if isinstance(result, dict) and self.func.__name__ == 'load_epg':
                self.epg_loaded.emit(result)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class QtHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class IPTVGeneratorGUI(QMainWindow):
    progress_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Channel Manager")
        self.setMinimumSize(1200, 800)
        
        # Set window icon
        self.setWindowIcon(qta.icon('fa5s.tv'))
        
        # Store all channels
        self.all_channels = []
        self.epg_data = {}
        
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
        self.search_input.textChanged.connect(self.apply_filters)
        search_layout.addWidget(self.search_input)
        filter_layout.addLayout(search_layout)

        # Category filter
        category_layout = QHBoxLayout()
        category_label = QLabel()
        category_label.setPixmap(qta.icon('fa5s.tags').pixmap(16, 16))
        category_layout.addWidget(category_label)
        self.category_combo = QComboBox()
        self.category_combo.addItems(['All', 'Movies', 'Sports', 'News', 'Entertainment', 'Music'])
        self.category_combo.currentTextChanged.connect(self.apply_filters)
        category_layout.addWidget(self.category_combo)
        filter_layout.addLayout(category_layout)

        # Country filter
        country_layout = QHBoxLayout()
        country_label = QLabel()
        country_label.setPixmap(qta.icon('fa5s.globe').pixmap(16, 16))
        country_layout.addWidget(country_label)
        self.country_edit = QLineEdit()
        self.country_edit.setPlaceholderText("Enter country...")
        self.country_edit.textChanged.connect(self.apply_filters)
        country_layout.addWidget(self.country_edit)
        filter_layout.addLayout(country_layout)

        # Official only filter
        self.official_only = QCheckBox()
        self.official_only.setText("Official iptv.org only")
        self.official_only.setIcon(qta.icon('fa5s.check-circle'))
        self.official_only.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.official_only)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # Create channels table
        self.channels_table = QTableWidget()
        self.channels_table.setColumnCount(6)  # Added column for EPG status
        self.channels_table.setHorizontalHeaderLabels(['Name', 'Category', 'Country', 'Source', 'EPG', 'Selected'])
        self.channels_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.channels_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.channels_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.channels_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.channels_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.channels_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        # Enable sorting
        self.channels_table.setSortingEnabled(True)
        self.channels_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        layout.addWidget(self.channels_table)

        # Selection buttons
        selection_layout = QHBoxLayout()
        
        # Add channel count label
        count_label = QLabel()
        count_label.setPixmap(qta.icon('fa5s.list').pixmap(16, 16))
        selection_layout.addWidget(count_label)
        self.channel_count_label = QLabel("Channels: 0")
        selection_layout.addWidget(self.channel_count_label)
        
        selection_layout.addStretch()
        
        # Select All button
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setIcon(qta.icon('fa5s.check-square'))
        self.select_all_btn.clicked.connect(lambda: self.toggle_all_selections(True))
        selection_layout.addWidget(self.select_all_btn)
        
        # Deselect All button
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.setIcon(qta.icon('fa5s.square'))
        self.deselect_all_btn.clicked.connect(lambda: self.toggle_all_selections(False))
        selection_layout.addWidget(self.deselect_all_btn)
        
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

        # Buttons layout
        buttons_layout = QHBoxLayout()
        
        # Load channels button
        self.load_button = QPushButton("Load Channels")
        self.load_button.setIcon(qta.icon('fa5s.sync'))
        self.load_button.clicked.connect(self.load_all_channels)
        buttons_layout.addWidget(self.load_button)
        
        # Generate button
        self.generate_button = QPushButton("Generate Selected")
        self.generate_button.setIcon(qta.icon('fa5s.play-circle'))
        self.generate_button.clicked.connect(self.generate)
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

        # Connect log signal and set up logging
        self.log_signal.connect(self.log_message)
        self.setup_logging()

    def load_all_channels(self):
        """Load channels from all sources"""
        self.progress_bar.setValue(0)
        self.load_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        
        # Create worker thread for channel loading
        self.worker = WorkerThread(self.load_channels)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_channels_loaded)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def load_channels(self):
        """Load channels from various sources"""
        try:
            self.progress_signal.emit("Loading channels...")
            generator = iptv_generator.PlaylistGenerator()
            channels = []
            
            # Load online sources
            for source in generator.PLAYLIST_SOURCES:
                try:
                    self.progress_signal.emit(f"Loading channels from {source['name']}...")
                    response = generator.session.get(source['url'])
                    response.raise_for_status()
                    content = response.text
                    
                    if not content:
                        self.log_signal.emit(f"Warning: Empty content from {source['name']}")
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
                                            group=extinf_data.get('group-title', ''),
                                            url=url,
                                            tvg_id=extinf_data.get('tvg-id', ''),
                                            tvg_logo=extinf_data.get('tvg-logo', ''),
                                            source=source['name']
                                        )
                                        channels.append(channel)
                                        source_channels += 1
                            except Exception as e:
                                self.log_signal.emit(f"Error parsing channel in {source['name']}: {str(e)}")
                            i += 2
                        else:
                            i += 1
                    
                    self.log_signal.emit(f"Loaded {source_channels} channels from {source['name']}")
                            
                except Exception as e:
                    self.log_signal.emit(f"Error loading source {source['name']}: {str(e)}")
                    continue
                    
            # Load local playlists
            local_m3u_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_m3u')
            if os.path.exists(local_m3u_dir):
                for filename in os.listdir(local_m3u_dir):
                    if filename.endswith('.m3u') or filename.endswith('.m3u8'):
                        try:
                            playlist_path = os.path.join(local_m3u_dir, filename)
                            self.progress_signal.emit(f"Loading local playlist: {filename}")
                            
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
                                                    group=extinf_data.get('group-title', ''),
                                                    url=url,
                                                    tvg_id=extinf_data.get('tvg-id', ''),
                                                    tvg_logo=extinf_data.get('tvg-logo', ''),
                                                    source=f"local.{filename}"
                                                )
                                                channels.append(channel)
                                                local_channels += 1
                                    except Exception as e:
                                        self.log_signal.emit(f"Error parsing channel in {filename}: {str(e)}")
                                    i += 2
                                else:
                                    i += 1
                                    
                            self.log_signal.emit(f"Loaded {local_channels} channels from {filename}")
                                    
                        except Exception as e:
                            self.log_signal.emit(f"Error loading local playlist {filename}: {str(e)}")
                            continue

            if not channels:
                raise Exception("No channels were loaded from any source")

            self.all_channels = channels
            self.log_signal.emit(f"Successfully loaded {len(channels)} channels total")
            
            # After channels are loaded, load EPG
            self.progress_signal.emit("Loading EPG data...")
            self.load_epg()
            
        except Exception as e:
            self.error_signal.emit(str(e))

    def load_epg(self):
        """Load EPG data and update channel information"""
        try:
            self.progress_signal.emit("Loading EPG data...")
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
                        self.log_signal.emit(f"Failed to decompress content from {url}: {str(e)}")
                        return content.decode('utf-8', errors='ignore')
                return content.decode('utf-8', errors='ignore')
            
            # Load EPG from each source
            for epg_source in EPGFetcher.EPG_SOURCES:
                try:
                    self.progress_signal.emit(f"Loading EPG from {epg_source['name']}...")
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
                            channel_id = programme.get('channel')
                            if channel_id and channel_id not in epg_data:
                                epg_data[channel_id] = True
                                epg_data[channel_id.lower()] = True
                                epg_data[channel_id.replace(' ', '')] = True
                                source_channels += 1
                                
                        self.log_signal.emit(f"Loaded {source_channels} channel EPG data from {epg_source['name']}")
                                
                    except ET.ParseError as e:
                        self.log_signal.emit(f"Error parsing EPG XML from {epg_source['name']}: {str(e)}")
                        continue
                            
                except Exception as e:
                    self.log_signal.emit(f"Error loading EPG source {epg_source['name']}: {str(e)}")
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
            
            self.log_signal.emit(f"EPG data loaded for {epg_count} channels ({(epg_count/len(self.all_channels)*100):.1f}%)")
            return epg_data
            
        except Exception as e:
            self.error_signal.emit(f"EPG loading error: {str(e)}")
            return {}

    def on_channels_loaded(self):
        """Handle completion of channel loading"""
        self.load_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.progress_bar.setValue(100)
        
        # Update the table with loaded channels
        self.update_table(self.all_channels)
        self.apply_filters()  # Apply any active filters
        
        QMessageBox.information(self, "Loading Complete", 
                              f"Loaded {len(self.all_channels)} channels\n"
                              f"EPG data available for {sum(1 for c in self.all_channels if c.has_epg)} channels")

    def apply_filters(self):
        if not self.all_channels:
            return

        search_text = self.search_input.text().lower()
        category = self.category_combo.currentText()
        country = self.country_edit.text().lower()
        official_only = self.official_only.isChecked()

        filtered_channels = []
        for channel in self.all_channels:
            # Check source filter
            if official_only and not channel.source.startswith('iptv-org'):
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
        self.log_signal.emit(f"Showing {len(filtered_channels)} channels after filtering")

    def update_channels_table(self, channels):
        self.channels_table.setRowCount(len(channels))
        for row, channel in enumerate(channels):
            # Name
            name_item = QTableWidgetItem(channel.name)
            name_item.setData(Qt.UserRole, channel)  # Store channel object for sorting
            self.channels_table.setItem(row, 0, name_item)
            
            # Category
            category_item = QTableWidgetItem(channel.group)
            self.channels_table.setItem(row, 1, category_item)
            
            # Country
            country = channel.tvg_id.split('.')[0] if '.' in channel.tvg_id else ''
            country_item = QTableWidgetItem(country)
            self.channels_table.setItem(row, 2, country_item)
            
            # Source
            source_item = QTableWidgetItem(channel.source)
            self.channels_table.setItem(row, 3, source_item)
            
            # EPG
            epg_item = QTableWidgetItem("Yes" if channel.has_epg else "No")
            self.channels_table.setItem(row, 4, epg_item)
            
            # Selected
            selected_item = QTableWidgetItem()
            selected_item.setFlags(selected_item.flags() | Qt.ItemIsUserCheckable)
            selected_item.setCheckState(Qt.Checked if channel.is_official else Qt.Unchecked)
            self.channels_table.setItem(row, 5, selected_item)

        # Set custom sort role for all items
        for row in range(self.channels_table.rowCount()):
            for col in range(self.channels_table.columnCount()):
                item = self.channels_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, item.text().lower())  # Case-insensitive sorting

        self.update_channel_count()

    def toggle_all_selections(self, select: bool):
        """Toggle all visible channels' selection state"""
        for row in range(self.channels_table.rowCount()):
            checkbox_item = self.channels_table.item(row, 5)
            if checkbox_item:
                checkbox_item.setCheckState(Qt.Checked if select else Qt.Unchecked)
        
        state = "Selected" if select else "Deselected"
        self.log_signal.emit(f"{state} all {self.channels_table.rowCount()} visible channels")

    def generate(self):
        selected_channels = []
        for row in range(self.channels_table.rowCount()):
            if self.channels_table.item(row, 5).checkState() == Qt.Checked:
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
        self.worker.finished.connect(self.generation_finished)
        self.worker.error.connect(self.generation_error)
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
            logging.error(f"Error generating output: {str(e)}")
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
        self.log_output.append(message)

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
        selected_count = sum(1 for row in range(self.channels_table.rowCount()) if self.channels_table.item(row, 5).checkState() == Qt.Checked)
        self.channel_count_label.setText(f"Channels: {selected_count}")

    def update_channel_count(self):
        self.channel_count_label.setText(f"Channels: {self.channels_table.rowCount()}")

    def update_table(self, channels):
        self.channels_table.setRowCount(len(channels))
        for row, channel in enumerate(channels):
            # Name
            name_item = QTableWidgetItem(channel.name)
            name_item.setData(Qt.UserRole, channel)  # Store channel object for sorting
            self.channels_table.setItem(row, 0, name_item)
            
            # Category
            category_item = QTableWidgetItem(channel.group)
            self.channels_table.setItem(row, 1, category_item)
            
            # Country
            country = channel.tvg_id.split('.')[0] if '.' in channel.tvg_id else ''
            country_item = QTableWidgetItem(country)
            self.channels_table.setItem(row, 2, country_item)
            
            # Source
            source_item = QTableWidgetItem(channel.source)
            self.channels_table.setItem(row, 3, source_item)
            
            # EPG
            epg_item = QTableWidgetItem("Yes" if channel.has_epg else "No")
            self.channels_table.setItem(row, 4, epg_item)
            
            # Selected
            selected_item = QTableWidgetItem()
            selected_item.setFlags(selected_item.flags() | Qt.ItemIsUserCheckable)
            selected_item.setCheckState(Qt.Checked if channel.is_official else Qt.Unchecked)
            self.channels_table.setItem(row, 5, selected_item)

        # Set custom sort role for all items
        for row in range(self.channels_table.rowCount()):
            for col in range(self.channels_table.columnCount()):
                item = self.channels_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, item.text().lower())  # Case-insensitive sorting

        self.update_channel_count()

    def update_progress(self, message):
        """Update progress bar and log message"""
        self.log_signal.emit(message)
        self.progress_bar.setValue(50)  # Set to 50% during channel loading

    def on_error(self, error_message):
        """Handle errors during loading"""
        self.load_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

def main():
    app = QApplication(sys.argv)
    window = IPTVGeneratorGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

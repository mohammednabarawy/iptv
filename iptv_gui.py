import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QLineEdit, QComboBox, 
                           QPushButton, QCheckBox, QGroupBox, QProgressBar,
                           QTextEdit, QFileDialog, QMessageBox, QTabWidget,
                           QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import iptv_generator
import logging
import os

class WorkerThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.function(*self.args, **self.kwargs)
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
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Generator")
        self.setMinimumSize(1000, 700)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Create tab widget
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # Create tabs
        local_tab = QWidget()
        remote_tab = QWidget()
        tab_widget.addTab(local_tab, "Local Playlists")
        tab_widget.addTab(remote_tab, "Remote Sources")

        # Setup local playlists tab
        local_layout = QVBoxLayout(local_tab)
        
        # Local playlists list
        playlists_group = QGroupBox("Available Local Playlists")
        playlists_layout = QVBoxLayout()
        
        # Add search box for playlists
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.playlist_search = QLineEdit()
        self.playlist_search.textChanged.connect(self.filter_playlists)
        search_layout.addWidget(self.playlist_search)
        playlists_layout.addLayout(search_layout)

        # Add playlist categories
        categories_layout = QHBoxLayout()
        categories_layout.addWidget(QLabel("Quick Filters:"))
        for category in ["All", "Sports", "Movies", "News", "Entertainment", "Music"]:
            btn = QPushButton(category)
            btn.clicked.connect(lambda checked, cat=category: self.filter_by_category(cat))
            categories_layout.addWidget(btn)
        playlists_layout.addLayout(categories_layout)

        # Playlist list
        self.playlist_list = QListWidget()
        self.playlist_list.setSelectionMode(QListWidget.MultiSelection)
        playlists_layout.addWidget(self.playlist_list)
        
        playlists_group.setLayout(playlists_layout)
        local_layout.addWidget(playlists_group)

        # Setup remote sources tab
        remote_layout = QVBoxLayout(remote_tab)
        
        # Remote sources group
        sources_group = QGroupBox("Remote IPTV Sources")
        sources_layout = QVBoxLayout()
        
        # Add source checkboxes
        self.source_checkboxes = {}
        for source in iptv_generator.PlaylistGenerator.PLAYLIST_SOURCES:
            checkbox = QCheckBox(source['name'])
            self.source_checkboxes[source['name']] = checkbox
            sources_layout.addWidget(checkbox)
        
        sources_group.setLayout(sources_layout)
        remote_layout.addWidget(sources_group)

        # Filters Group (in remote tab)
        filters_group = QGroupBox("Filters")
        filters_layout = QVBoxLayout()

        # Category filter
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(['', 'movies', 'entertainment', 'sports', 
                                    'news', 'documentary', 'music'])
        category_layout.addWidget(self.category_combo)
        filters_layout.addLayout(category_layout)

        # Country filter
        country_layout = QHBoxLayout()
        country_layout.addWidget(QLabel("Country:"))
        self.country_edit = QLineEdit()
        country_layout.addWidget(self.country_edit)
        filters_layout.addLayout(country_layout)

        filters_group.setLayout(filters_layout)
        remote_layout.addWidget(filters_group)

        # Output Options Group (common for both tabs)
        output_group = QGroupBox("Output Options")
        output_layout = QVBoxLayout()

        # M3U output path
        m3u_layout = QHBoxLayout()
        m3u_layout.addWidget(QLabel("M3U Output:"))
        self.m3u_path = QLineEdit("merged_playlist.m3u")
        m3u_layout.addWidget(self.m3u_path)
        self.m3u_browse = QPushButton("Browse")
        self.m3u_browse.clicked.connect(lambda: self.browse_file("M3U"))
        m3u_layout.addWidget(self.m3u_browse)
        output_layout.addLayout(m3u_layout)

        # EPG output path
        epg_layout = QHBoxLayout()
        epg_layout.addWidget(QLabel("EPG Output:"))
        self.epg_path = QLineEdit("guide.xml")
        epg_layout.addWidget(self.epg_path)
        self.epg_browse = QPushButton("Browse")
        self.epg_browse.clicked.connect(lambda: self.browse_file("EPG"))
        epg_layout.addWidget(self.epg_browse)
        output_layout.addLayout(epg_layout)

        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        # Progress bar
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Generate button
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self.generate)
        layout.addWidget(self.generate_button)

        # Connect log signal and set up logging
        self.log_signal.connect(self.log_message)
        self.setup_logging()

        # Load local playlists
        self.load_local_playlists()

    def load_local_playlists(self):
        self.playlist_list.clear()
        playlist_gen = iptv_generator.PlaylistGenerator()
        for playlist in playlist_gen.local_playlists:
            item = QListWidgetItem(os.path.basename(playlist))
            item.setData(Qt.UserRole, playlist)
            self.playlist_list.addItem(item)

    def filter_playlists(self):
        search_text = self.playlist_search.text().lower()
        for i in range(self.playlist_list.count()):
            item = self.playlist_list.item(i)
            item.setHidden(search_text not in item.text().lower())

    def filter_by_category(self, category):
        if category == "All":
            self.playlist_search.clear()
        else:
            self.playlist_search.setText(category.lower())

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

    def generate(self):
        # Disable generate button
        self.generate_button.setEnabled(False)
        self.log_output.clear()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress

        # Get selected local playlists
        selected_local = []
        for item in self.playlist_list.selectedItems():
            selected_local.append(item.data(Qt.UserRole))

        # Get selected remote sources
        selected_remote = [name for name, checkbox in self.source_checkboxes.items() 
                         if checkbox.isChecked()]

        if not selected_local and not selected_remote:
            QMessageBox.warning(self, "Warning", "Please select at least one playlist source.")
            self.generate_button.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            return

        # Create worker thread
        self.worker = WorkerThread(
            self.generate_playlist_and_epg,
            selected_local,
            selected_remote,
            self.category_combo.currentText(),
            self.country_edit.text(),
            self.m3u_path.text(),
            self.epg_path.text()
        )
        self.worker.finished.connect(self.generation_finished)
        self.worker.error.connect(self.generation_error)
        self.worker.start()

    def generate_playlist_and_epg(self, local_playlists, remote_sources, 
                                category, country, m3u_path, epg_path):
        try:
            # Initialize generators
            playlist_gen = iptv_generator.PlaylistGenerator()
            epg_fetcher = iptv_generator.EPGFetcher()

            # Process local playlists
            merged_content = "#EXTM3U\n"
            for playlist in local_playlists:
                with open(playlist, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if category:
                        # Filter by category if specified
                        lines = content.split('\n')
                        filtered_lines = []
                        for i in range(len(lines)):
                            if lines[i].startswith('#EXTINF'):
                                if category.lower() in lines[i].lower():
                                    filtered_lines.extend([lines[i], lines[i+1]])
                        content = '\n'.join(filtered_lines)
                    merged_content += content + "\n"

            # Process remote sources if any
            if remote_sources:
                for source in remote_sources:
                    try:
                        url = next(s['url'] for s in playlist_gen.PLAYLIST_SOURCES if s['name'] == source)
                        response = playlist_gen.session.get(url)
                        response.raise_for_status()
                        content = response.text
                        if category:
                            # Filter remote content by category
                            lines = content.split('\n')
                            filtered_lines = []
                            for i in range(len(lines)):
                                if lines[i].startswith('#EXTINF'):
                                    if category.lower() in lines[i].lower():
                                        filtered_lines.extend([lines[i], lines[i+1]])
                            content = '\n'.join(filtered_lines)
                        merged_content += content + "\n"
                    except Exception as e:
                        logging.error(f"Error fetching {source}: {str(e)}")

            # Add EPG mapping
            merged_content = playlist_gen.add_epg_mapping(merged_content)
            
            # Save merged playlist
            with open(m3u_path, 'w', encoding='utf-8') as f:
                f.write(merged_content)

            # Generate EPG
            epg_content = epg_fetcher.fetch_epg()
            
            # Save EPG
            with open(epg_path, 'w', encoding='utf-8') as f:
                f.write(epg_content)

        except Exception as e:
            logging.error(f"Error generating playlist: {str(e)}")
            raise

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

def main():
    app = QApplication(sys.argv)
    window = IPTVGeneratorGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

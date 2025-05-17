import sys
import logging
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                            QTableWidgetItem, QPushButton, QHeaderView, QLabel)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
import qtawesome as qta

logger = logging.getLogger(__name__)

class FavoritesTab(QWidget):
    """Tab for displaying and managing favorite channels"""
    
    # Signals
    play_signal = pyqtSignal(str, str)  # url, name
    remove_signal = pyqtSignal(str)     # url
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.favorites = []
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        try:
            # Create main layout
            main_layout = QVBoxLayout(self)
            
            # Title
            title_label = QLabel("Favorite Channels")
            title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            title_label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(title_label)
            
            # Create favorites table
            self.favorites_table = QTableWidget()
            self.favorites_table.setColumnCount(6)
            self.favorites_table.setHorizontalHeaderLabels([
                "Name", "Group", "Resolution", "Content Type", "Added", "Actions"
            ])
            
            # Set column resize modes
            self.favorites_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.favorites_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.favorites_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.favorites_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.favorites_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            self.favorites_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            
            main_layout.addWidget(self.favorites_table)
            
            # Refresh button
            refresh_button = QPushButton("Refresh")
            refresh_button.setIcon(qta.icon('fa5s.sync'))
            refresh_button.clicked.connect(self.load_favorites)
            main_layout.addWidget(refresh_button)
            
            # Load favorites
            self.load_favorites()
            
        except Exception as e:
            logger.error(f"Error initializing favorites UI: {str(e)}", exc_info=True)
            
    def load_favorites(self):
        """Load favorite channels from the database"""
        try:
            # Clear table
            self.favorites_table.setRowCount(0)
            
            # Get favorites from database
            self.favorites = self.data_manager.get_favorites()
            
            # Add favorites to table
            for i, favorite in enumerate(self.favorites):
                row = self.favorites_table.rowCount()
                self.favorites_table.insertRow(row)
                
                # Channel name
                name_item = QTableWidgetItem(favorite.get('name', ''))
                self.favorites_table.setItem(row, 0, name_item)
                
                # Channel group
                group_item = QTableWidgetItem(favorite.get('group_title', ''))
                self.favorites_table.setItem(row, 1, group_item)
                
                # Resolution
                resolution_item = QTableWidgetItem(favorite.get('resolution', ''))
                self.favorites_table.setItem(row, 2, resolution_item)
                
                # Content type
                content_type_item = QTableWidgetItem(favorite.get('content_type', ''))
                self.favorites_table.setItem(row, 3, content_type_item)
                
                # Added date
                added_item = QTableWidgetItem(favorite.get('added_at', ''))
                self.favorites_table.setItem(row, 4, added_item)
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(0, 0, 0, 0)
                
                # Play button
                play_button = QPushButton()
                play_button.setIcon(qta.icon('fa5s.play'))
                play_button.setToolTip("Play")
                play_button.clicked.connect(lambda checked, url=favorite.get('url', ''), name=favorite.get('name', ''): 
                                           self.play_signal.emit(url, name))
                actions_layout.addWidget(play_button)
                
                # Remove button
                remove_button = QPushButton()
                remove_button.setIcon(qta.icon('fa5s.trash'))
                remove_button.setToolTip("Remove from favorites")
                remove_button.clicked.connect(lambda checked, url=favorite.get('url', ''): 
                                             self.remove_favorite(url))
                actions_layout.addWidget(remove_button)
                
                self.favorites_table.setCellWidget(row, 5, actions_widget)
                
            logger.info(f"Loaded {len(self.favorites)} favorite channels")
            
        except Exception as e:
            logger.error(f"Error loading favorites: {str(e)}", exc_info=True)
            
    def remove_favorite(self, url):
        """Remove a channel from favorites"""
        try:
            # Remove from database
            success = self.data_manager.remove_from_favorites(url)
            
            if success:
                # Reload favorites
                self.load_favorites()
                
                # Emit signal
                self.remove_signal.emit(url)
                
                logger.info(f"Removed channel from favorites: {url}")
            else:
                logger.error(f"Failed to remove channel from favorites: {url}")
                
        except Exception as e:
            logger.error(f"Error removing favorite: {str(e)}", exc_info=True)

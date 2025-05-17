import sys
import logging
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
                            QTableWidgetItem, QPushButton, QHeaderView, QLabel)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
import qtawesome as qta

logger = logging.getLogger(__name__)

class WatchHistoryTab(QWidget):
    """Tab for displaying watch history"""
    
    # Signals
    play_signal = pyqtSignal(str, str)  # url, name
    favorite_signal = pyqtSignal(str)   # url
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.history = []
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        try:
            # Create main layout
            main_layout = QVBoxLayout(self)
            
            # Title
            title_label = QLabel("Watch History")
            title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
            title_label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(title_label)
            
            # Create history table
            self.history_table = QTableWidget()
            self.history_table.setColumnCount(6)
            self.history_table.setHorizontalHeaderLabels([
                "Name", "Group", "Resolution", "Content Type", "Watched", "Actions"
            ])
            
            # Set column resize modes
            self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
            self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            
            main_layout.addWidget(self.history_table)
            
            # Refresh button
            refresh_button = QPushButton("Refresh")
            refresh_button.setIcon(qta.icon('fa5s.sync'))
            refresh_button.clicked.connect(self.load_history)
            main_layout.addWidget(refresh_button)
            
            # Load history
            self.load_history()
            
        except Exception as e:
            logger.error(f"Error initializing watch history UI: {str(e)}", exc_info=True)
            
    def load_history(self):
        """Load watch history from the database"""
        try:
            # Clear table
            self.history_table.setRowCount(0)
            
            # Get history from database
            self.history = self.data_manager.get_watch_history()
            
            # Add history items to table
            for i, item in enumerate(self.history):
                row = self.history_table.rowCount()
                self.history_table.insertRow(row)
                
                # Channel name
                name_item = QTableWidgetItem(item.get('name', ''))
                self.history_table.setItem(row, 0, name_item)
                
                # Channel group
                group_item = QTableWidgetItem(item.get('group_title', ''))
                self.history_table.setItem(row, 1, group_item)
                
                # Resolution
                resolution_item = QTableWidgetItem(item.get('resolution', ''))
                self.history_table.setItem(row, 2, resolution_item)
                
                # Content type
                content_type_item = QTableWidgetItem(item.get('content_type', ''))
                self.history_table.setItem(row, 3, content_type_item)
                
                # Format watched time
                watched_at = item.get('watched_at', '')
                if watched_at:
                    try:
                        # Parse the timestamp
                        dt = datetime.fromisoformat(watched_at.replace('Z', '+00:00'))
                        # Format as a readable string
                        watched_at = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        pass  # Keep original format if parsing fails
                
                watched_item = QTableWidgetItem(watched_at)
                self.history_table.setItem(row, 4, watched_item)
                
                # Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(0, 0, 0, 0)
                
                # Play button
                play_button = QPushButton()
                play_button.setIcon(qta.icon('fa5s.play'))
                play_button.setToolTip("Play")
                play_button.clicked.connect(lambda checked, url=item.get('url', ''), name=item.get('name', ''): 
                                           self.play_signal.emit(url, name))
                actions_layout.addWidget(play_button)
                
                # Favorite button
                is_favorite = self.data_manager.is_favorite(item.get('url', ''))
                favorite_button = QPushButton()
                favorite_button.setIcon(qta.icon('fa5s.heart' if is_favorite else 'fa5s.heart', color='red' if is_favorite else 'gray'))
                favorite_button.setToolTip("Add to favorites" if not is_favorite else "Remove from favorites")
                favorite_button.clicked.connect(lambda checked, url=item.get('url', ''): 
                                              self.toggle_favorite(url))
                actions_layout.addWidget(favorite_button)
                
                self.history_table.setCellWidget(row, 5, actions_widget)
                
            logger.info(f"Loaded {len(self.history)} watch history items")
            
        except Exception as e:
            logger.error(f"Error loading watch history: {str(e)}", exc_info=True)
            
    def toggle_favorite(self, url):
        """Toggle favorite status for a channel"""
        try:
            is_favorite = self.data_manager.is_favorite(url)
            
            if is_favorite:
                success = self.data_manager.remove_from_favorites(url)
                logger.info(f"Removed channel from favorites: {url}")
            else:
                success = self.data_manager.add_to_favorites(url)
                logger.info(f"Added channel to favorites: {url}")
                
                # Emit signal
                self.favorite_signal.emit(url)
                
            # Reload history to update favorite icons
            self.load_history()
                
        except Exception as e:
            logger.error(f"Error toggling favorite: {str(e)}", exc_info=True)

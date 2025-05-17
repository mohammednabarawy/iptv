import sys
import logging
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QFrame, QGridLayout, QSizePolicy, QSpacerItem,
                            QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette, QFont

logger = logging.getLogger(__name__)

class StatCard(QFrame):
    """A card widget to display a statistic with title and value"""
    
    def __init__(self, title, value, icon=None, color="#3498db"):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setStyleSheet(f"background-color: {color}; color: white; border-radius: 5px;")
        
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Value
        value_label = QLabel(str(value))
        value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)
        
        # Set minimum size
        self.setMinimumHeight(100)
        
class Dashboard(QWidget):
    """Dashboard widget to display statistics about the channel collection"""
    
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        try:
            # Create main layout
            main_layout = QVBoxLayout(self)
            
            # Title
            title_label = QLabel("Channel Collection Dashboard")
            title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
            title_label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(title_label)
            
            # Stats cards layout
            cards_layout = QHBoxLayout()
            
            # Get statistics
            stats = self.data_manager.get_channel_statistics()
            
            # Create stat cards
            self.total_card = StatCard("Total Channels", stats.get('total_channels', 0), color="#3498db")
            self.working_card = StatCard("Working Channels", stats.get('working_channels', 0), color="#2ecc71")
            self.epg_card = StatCard("Channels with EPG", stats.get('channels_with_epg', 0), color="#9b59b6")
            self.favorites_card = StatCard("Favorites", stats.get('favorite_channels', 0), color="#e74c3c")
            self.watched_card = StatCard("Watched Channels", stats.get('watched_channels', 0), color="#f39c12")
            
            # Add cards to layout
            cards_layout.addWidget(self.total_card)
            cards_layout.addWidget(self.working_card)
            cards_layout.addWidget(self.epg_card)
            cards_layout.addWidget(self.favorites_card)
            cards_layout.addWidget(self.watched_card)
            
            main_layout.addLayout(cards_layout)
            
            # Create tables layout
            tables_layout = QHBoxLayout()
            
            # Create resolution distribution table
            resolution_group = self.create_resolution_table(stats.get('resolution_counts', {}))
            tables_layout.addWidget(resolution_group)
            
            # Create content type distribution table
            content_group = self.create_content_type_table(stats.get('content_type_counts', {}))
            tables_layout.addWidget(content_group)
            
            main_layout.addLayout(tables_layout)
            
            # Top groups table
            top_groups_group = self.create_top_groups_table(stats.get('top_groups', {}))
            main_layout.addWidget(top_groups_group)
            
            # Add spacer at the bottom
            main_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
            
        except Exception as e:
            logger.error(f"Error initializing dashboard UI: {str(e)}", exc_info=True)
            
    def create_resolution_table(self, resolution_counts):
        """Create a table for resolution distribution"""
        try:
            # Create frame
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # Create layout
            layout = QVBoxLayout(frame)
            
            # Add title
            title = QLabel("Resolution Distribution")
            title.setStyleSheet("font-size: 14px; font-weight: bold;")
            title.setAlignment(Qt.AlignCenter)
            layout.addWidget(title)
            
            # Create table
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Resolution", "Count"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            
            # Add data
            table.setRowCount(len(resolution_counts))
            for i, (resolution, count) in enumerate(resolution_counts.items()):
                if resolution and count > 0:
                    # Resolution
                    resolution_item = QTableWidgetItem(resolution)
                    table.setItem(i, 0, resolution_item)
                    
                    # Count
                    count_item = QTableWidgetItem(str(count))
                    table.setItem(i, 1, count_item)
            
            layout.addWidget(table)
            
            return frame
            
        except Exception as e:
            logger.error(f"Error creating resolution table: {str(e)}", exc_info=True)
            return QLabel("Error creating table")
            
    def create_content_type_table(self, content_type_counts):
        """Create a table for content type distribution"""
        try:
            # Create frame
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # Create layout
            layout = QVBoxLayout(frame)
            
            # Add title
            title = QLabel("Content Type Distribution")
            title.setStyleSheet("font-size: 14px; font-weight: bold;")
            title.setAlignment(Qt.AlignCenter)
            layout.addWidget(title)
            
            # Create table
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Content Type", "Count"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            
            # Add data
            table.setRowCount(len(content_type_counts))
            for i, (content_type, count) in enumerate(content_type_counts.items()):
                if content_type and count > 0:
                    # Content type
                    content_type_item = QTableWidgetItem(content_type)
                    table.setItem(i, 0, content_type_item)
                    
                    # Count
                    count_item = QTableWidgetItem(str(count))
                    table.setItem(i, 1, count_item)
            
            layout.addWidget(table)
            
            return frame
            
        except Exception as e:
            logger.error(f"Error creating content type table: {str(e)}", exc_info=True)
            return QLabel("Error creating table")
            
    def create_top_groups_table(self, top_groups):
        """Create a table for top channel groups"""
        try:
            # Create frame
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # Create layout
            layout = QVBoxLayout(frame)
            
            # Add title
            title = QLabel("Top Channel Groups")
            title.setStyleSheet("font-size: 14px; font-weight: bold;")
            title.setAlignment(Qt.AlignCenter)
            layout.addWidget(title)
            
            # Create table
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Group", "Channel Count"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            
            # Add data
            table.setRowCount(len(top_groups))
            for i, (group, count) in enumerate(top_groups.items()):
                if group and count > 0:
                    # Group
                    group_item = QTableWidgetItem(group)
                    table.setItem(i, 0, group_item)
                    
                    # Count with progress bar
                    count_item = QTableWidgetItem(str(count))
                    table.setItem(i, 1, count_item)
            
            layout.addWidget(table)
            
            return frame
            
        except Exception as e:
            logger.error(f"Error creating top groups table: {str(e)}", exc_info=True)
            return QLabel("Error creating table")
            
    def refresh(self):
        """Refresh the dashboard with updated statistics"""
        try:
            # Get updated statistics
            stats = self.data_manager.get_channel_statistics()
            
            # Update stat cards
            self.total_card.findChild(QLabel, "", Qt.FindChildrenRecursively).setText(str(stats.get('total_channels', 0)))
            self.working_card.findChild(QLabel, "", Qt.FindChildrenRecursively).setText(str(stats.get('working_channels', 0)))
            self.epg_card.findChild(QLabel, "", Qt.FindChildrenRecursively).setText(str(stats.get('channels_with_epg', 0)))
            self.favorites_card.findChild(QLabel, "", Qt.FindChildrenRecursively).setText(str(stats.get('favorite_channels', 0)))
            self.watched_card.findChild(QLabel, "", Qt.FindChildrenRecursively).setText(str(stats.get('watched_channels', 0)))
            
            # Re-initialize UI to update tables
            # This is a simple approach; a more optimized solution would update the tables directly
            self.init_ui()
            
        except Exception as e:
            logger.error(f"Error refreshing dashboard: {str(e)}", exc_info=True)


class StatCard(QFrame):
    """A card widget to display a statistic with a title and value"""
    
    def __init__(self, title, value, color="#3498db"):
        super().__init__()
        self.title = title
        self.value = value
        self.color = color
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        try:
            # Set frame style
            self.setFrameShape(QFrame.StyledPanel)
            self.setFrameShadow(QFrame.Raised)
            self.setStyleSheet(f"border: 2px solid {self.color}; border-radius: 8px;")
            
            # Create layout
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 10)
            
            # Title label
            title_label = QLabel(self.title)
            title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            title_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(title_label)
            
            # Value label
            value_label = QLabel(str(self.value))
            value_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {self.color};")
            value_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(value_label)
            
            # Set minimum size
            self.setMinimumSize(150, 100)
            
        except Exception as e:
            logger.error(f"Error initializing stat card UI: {str(e)}", exc_info=True)

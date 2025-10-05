#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A UI application for managing Draw Things data using PyQt6.
"""
import sys
import os
import subprocess
import sqlite3
import random
import argparse
import sys
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QLabel, QListWidgetItem, QScrollArea, QGridLayout,
    QComboBox, QCheckBox, QLineEdit, QMessageBox
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QLinearGradient, QBrush, QPainterPath, QPixmap, QImage
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QTimer, QRectF, QRect
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from PIL import Image
import io
import flatbuffers
import ThumbnailHistoryNode
import ThumbnailHistoryHalfNode
import subprocess

# Global flags
VERBOSE = False
DEMO_MODE = False

# Define the color palette
theme = {
    "background": "#5a818d",
    "foreground": "#1d2f3d",
    "button": "#E6007E",
    "button_hover": "#FF52A1",
    "text": "#75BAC5",
    "sidebar": "#2E3B4E",
    "title_bar": "#FFB1D4",
}

class ClickableWidget(QWidget):
    clicked = pyqtSignal(object, object)  # widget, event

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected = False
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['foreground']};
                border: 2px solid transparent;
                border-radius: 4px;
            }}
        """)

    def setSelected(self, selected):
        self.selected = selected
        if selected:
            self.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme['foreground']};
                    border: 2px solid {theme['button']};
                    border-radius: 4px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme['foreground']};
                    border: 2px solid transparent;
                    border-radius: 4px;
                }}
            """)

    def mousePressEvent(self, event):
        self.clicked.emit(self, event)
        super().mousePressEvent(event)

class ClearableLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear_button_rect = None
        self._clear_enabled = True  # Enabled by default
        self.setClearButtonEnabled(True)

    def setClearButtonEnabled(self, enabled):
        self._clear_enabled = enabled
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self._clear_enabled and self.text():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Calculate the rect for the clear button (right side)
            icon_size = 10
            margin = 8
            clear_x = int(self.width() - icon_size - margin * 2)
            clear_y = int((self.height() - icon_size) / 2 + 3)
            clear_rect = QRect(clear_x, clear_y, icon_size, icon_size)
            self.clear_button_rect = clear_rect

            # Draw the 'x' symbol
            painter.setPen(QColor(theme['text']))  # Use theme text color
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Draw two crossing lines
            painter.drawLine(clear_rect.left(), clear_rect.top(),
                           clear_rect.right(), clear_rect.bottom())
            painter.drawLine(clear_rect.left(), clear_rect.bottom(),
                           clear_rect.right(), clear_rect.top())

    def mousePressEvent(self, event):
        if self._clear_enabled and self.clear_button_rect and self.clear_button_rect.contains(event.position().toPoint()):
            self.clear()
            self.textChanged.emit("")  # Emit signal to trigger refresh
        else:
            super().mousePressEvent(event)

class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(30)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.title_label = QLabel("ミスタースパーコル")
        self.title_label.setStyleSheet(f"""
            color: {theme['title_bar']};
            font-size: 18px;
            font-weight: bold;
            padding-left: 27px;
        """)
        self.layout.addWidget(self.title_label)
        self.layout.addStretch()

        self.min_button = QPushButton("-")
        self.min_button.setFixedSize(30, 30)
        self.min_button.clicked.connect(self.parent_window.showMinimized)
        self.layout.addWidget(self.min_button)

        self.max_button = QPushButton("[]")
        self.max_button.setFixedSize(30, 30)
        self.max_button.clicked.connect(self.toggle_maximize_restore)
        self.layout.addWidget(self.max_button)

        self.close_button = QPushButton("X")
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.parent_window.close)
        self.layout.addWidget(self.close_button)

        button_style = f"""
            QPushButton {{
                background-color: {theme['background']};
                color: {theme['text']};
                border: none;
                border-radius: 0px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:pressed {{
                background-color: {theme['button']};
            }}
        """
        self.min_button.setStyleSheet(button_style)
        self.max_button.setStyleSheet(button_style)
        self.close_button.setStyleSheet(button_style + "QPushButton:hover { background-color: #E81123; }")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parent_window.old_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.parent_window.old_pos:
            delta = event.globalPosition().toPoint() - self.parent_window.old_pos
            self.parent_window.move(
                self.parent_window.x() + delta.x(),
                self.parent_window.y() + delta.y()
            )
            self.parent_window.old_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.parent_window.old_pos = None
        super().mouseReleaseEvent(event)

    def toggle_maximize_restore(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.max_button.setText("[]")
        else:
            self.parent_window.showMaximized()
            self.max_button.setText("🗖")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Define colors
        sidebar_color = QColor(theme['sidebar'])
        background_color = QColor(theme['background'])

        # Create a gradient from sidebar to background
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, sidebar_color)
        gradient.setColorAt(1, background_color)

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw a rectangle for the title bar background
        painter.drawRect(self.rect())

        # Draw organic shapes blending from sidebar to main background
        # This is a simplified example, more complex shapes would require
        # more advanced path drawing.
        path = QPainterPath()
        path.moveTo(self.width() * 0.2, 0)
        path.cubicTo(
            self.width() * 0.3, self.height() * 0.8,
            self.width() * 0.7, self.height() * 0.2,
            self.width() * 0.8, self.height()
        )
        path.lineTo(self.width(), self.height())
        path.lineTo(self.width(), 0)
        path.closeSubpath()

        painter.fillPath(path, QBrush(background_color))

        super().paintEvent(event)


class App(QMainWindow):
    """
    Main application window.
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.old_pos = None

        self.setWindowIcon(QIcon("./images/ms.png"))
        self.setWindowTitle("ミスタースパーコル")
        self.setGeometry(100, 100, 1040, 600)

        self.data_path = os.path.expanduser(
            "~/Library/Containers/com.liuliu.draw-things/Data"
        )

        # Set main window style
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {theme['background']};
            }}
        """)

        # Main widget and layout
        main_widget = QWidget()
        main_widget.setStyleSheet(f"""
            QWidget {{
        
                background-color: {theme['background']};
                color: {theme['text']};
            }}
        """)
        # Create a central widget to hold everything
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        app_layout = QVBoxLayout(central_widget)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        app_layout.addWidget(self.title_bar)

        main_content_widget = QWidget()
        main_content_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['background']};
                color: {theme['text']};
            }}
        """)
        app_layout.addWidget(main_content_widget)
        main_layout = QHBoxLayout(main_content_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['sidebar']};
                border-right: 2px solid {theme['sidebar']};
            }}
            QLabel {{
                color: {theme['foreground']};
            }}
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)

        logo_label = QLabel("Mr Sparkru ✨")
        logo_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['title_bar']};
                font-size: 18px;
                font-weight: bold;
                qproperty-alignment: AlignCenter;
                margin-bottom: 20px;
            }}
        """)
        sidebar_layout.addWidget(logo_label)

        button_style = f"""
            QPushButton {{
                background-color: {theme['button']};
                color: {theme['foreground']};
                border: 1px solid {theme['button_hover']};
                border-radius: 6px;
                padding: 12px;
                text-align: center;
                font-weight: bold;
                min-width: 160px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
                border: 1px solid {theme['text']};
            }}
            QPushButton:pressed {{
                background-color: {theme['text']};
            }}
        """

        self.refresh_button = QPushButton("🔄 Refresh")
        self.refresh_button.setStyleSheet(button_style)
        self.refresh_button.clicked.connect(self.refresh_lists)
        sidebar_layout.addWidget(self.refresh_button)

        ## sidebar_layout.addSpacing(10)

        self.delete_models_button = QPushButton("🗂️ Delete Models")
        self.delete_models_button.setStyleSheet(button_style)
        self.delete_models_button.clicked.connect(self.delete_selected_models)
        sidebar_layout.addWidget(self.delete_models_button)

        self.delete_projects_button = QPushButton("📁 Delete Projects")
        self.delete_projects_button.setStyleSheet(button_style)
        self.delete_projects_button.clicked.connect(self.delete_selected_projects)
        sidebar_layout.addWidget(self.delete_projects_button)

        self.delete_images_button = QPushButton("🖼️ Delete Images")
        self.delete_images_button.setStyleSheet(button_style)
        self.delete_images_button.clicked.connect(self.delete_selected_images)
        sidebar_layout.addWidget(self.delete_images_button)

        sidebar_layout.addSpacing(10)

        self.undo_button = QPushButton("↶ Undo Last Action")
        self.undo_button.setStyleSheet(button_style)
        self.undo_button.clicked.connect(self.undo_last_action)
        sidebar_layout.addWidget(self.undo_button)

        # Mr sparkru images
        self.sparkru_images = ['ms_01.png', 'ms_02.png', 'ms_03.png', 'ms_04.png', 'ms_05.png', 'ms_06.png', 'ms_07.png', 'ms_08.png', 'ms_09.png', 'ms_10.png', 'ms_11.png', 'ms_12.png', 'ms_13.png', 'ms_14.png', 'ms_15.png', 'ms_16.png', 'ms_17.png', 'ms_18.png', 'ms_19.png', 'ms_20.png', 'ms_21.png', 'ms_22.png', 'ms_23.png', 'ms_24.png', 'ms_25.png', 'ms_26.png']
        self.animation_timer = None
        self.current_image_path = None

        # Mr sparkru image
        self.sparkru_label = QLabel()
        initial_image_path = random.choice(self.sparkru_images)
        self.set_sparkru_image(initial_image_path)
        sidebar_layout.addWidget(self.sparkru_label, alignment=Qt.AlignmentFlag.AlignCenter)

        sidebar_layout.addStretch()
        main_layout.addWidget(sidebar)

        # Content area with enhanced styling
        content_area = QWidget()
        content_area.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['background']};
                color: {theme['foreground']};
                border: 1px solid {theme['sidebar']};
                border-radius: 8px;
                margin: 10px 5px 5px 0px;
            }}
            QLabel {{
                color: {theme['foreground']};
                font-weight: bold;
                font-size: 14px;
                margin-bottom: 5px;
                qproperty-alignment: AlignCenter;
            }}
            QLineEdit {{
                background-color: {theme['foreground']};
                color: {theme['text']};
                border: 2px solid {theme['sidebar']};
                border-radius: 4px;
                padding: 5px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {theme['sidebar']};
            }}
            QComboBox {{
                background-color: {theme['foreground']};
                color: {theme['text']};
                border: 2px solid {theme['sidebar']};
                border-radius: 4px;
                padding: 4px;
                font-size: 12px;
            }}
            QComboBox:hover {{
                border-color: {theme['button']};
            }}
            QListWidget {{
                background-color: {theme['foreground']};
                color: {theme['text']};
                border: 2px solid {theme['sidebar']};
                border-radius: 4px;
                padding: 2px;
                font-size: 12px;
                alternate-background-color: {theme['background']};
            }}
            QListWidget::item {{
                padding: 4px;
                border-bottom: 1px solid {theme['sidebar']};
            }}
            QListWidget::item:hover {{
                background-color: {theme['button_hover']};
                color: {theme['foreground']};
            }}
            QListWidget::item:selected {{
                background-color: {theme['button']};
                color: {theme['foreground']};
            }}
            QCheckBox {{
                color: {theme['text']};
                font-weight: normal;
            }}
            QCheckBox::indicator {{
                border: 2px solid {theme['sidebar']};
                background-color: {theme['foreground']};
                border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {theme['button']};
                border-color: {theme['button_hover']};
            }}
            QScrollArea {{
                background-color: {theme['background']};
                border: 1px solid {theme['sidebar']};
                border-radius: 6px;
            }}
            QScrollBar:vertical {{
                background-color: {theme['sidebar']};
                border-radius: 4px;
            }}
            QScrollBar::handle {{
                background-color: {theme['button']};
                border-radius: 4px;
            }}
            QScrollBar::handle:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        content_layout = QHBoxLayout(content_area)
        content_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(content_area, 1)

        # Models list with enhanced styling
        models_widget = QWidget()
        models_layout = QVBoxLayout(models_widget)
        models_label = QLabel("🗂️ Models")
        models_layout.addWidget(models_label)

        # Add search box above sort combo
        self.model_search = ClearableLineEdit()
        self.model_search.setPlaceholderText("🔍 Search models...")
        self.model_search.textChanged.connect(self.refresh_lists)
        models_layout.addWidget(self.model_search)

        self.model_sort_combo = QComboBox()
        self.model_sort_combo.addItems(["A-Z", "Z-A", "Newest", "Oldest", "Largest", "Smallest"])
        self.model_sort_combo.currentIndexChanged.connect(self.refresh_lists)
        models_layout.addWidget(self.model_sort_combo)

        self.models_list = QListWidget()
        self.models_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.models_list.itemClicked.connect(self.update_button_states)
        self.models_list.itemSelectionChanged.connect(self.update_button_states)
        models_layout.addWidget(self.models_list)
        content_layout.addWidget(models_widget)

        # Projects list with enhanced styling
        projects_widget = QWidget()
        projects_layout = QVBoxLayout(projects_widget)
        projects_label = QLabel("📁 Projects")
        projects_layout.addWidget(projects_label)

        # Add search box above sort combo
        self.project_search = ClearableLineEdit()
        self.project_search.setPlaceholderText("🔍 Search projects...")
        self.project_search.textChanged.connect(self.refresh_lists)
        projects_layout.addWidget(self.project_search)

        self.project_sort_combo = QComboBox()
        self.project_sort_combo.addItems(["A-Z", "Z-A", "Newest", "Oldest", "Largest", "Smallest"])
        self.project_sort_combo.currentIndexChanged.connect(self.refresh_lists)
        projects_layout.addWidget(self.project_sort_combo)

        self.projects_list = QListWidget()
        self.projects_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.projects_list.itemClicked.connect(self.display_thumbnails)
        self.projects_list.itemSelectionChanged.connect(self.update_button_states)
        projects_layout.addWidget(self.projects_list)
        content_layout.addWidget(projects_widget)

        # Thumbnails display with enhanced styling
        self.thumbnail_scroll_area = QScrollArea()
        self.thumbnail_scroll_area.setWidgetResizable(True)
        self.thumbnail_scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {theme['background']};
                border: 2px solid {theme['sidebar']};
                border-radius: 8px;
            }}
        """)
        self.thumbnail_widget = QWidget()
        self.thumbnail_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['foreground']};
            }}
        """)
        self.thumbnail_layout = QGridLayout(self.thumbnail_widget)
        self.thumbnail_layout.setSpacing(10)
        self.thumbnail_layout.setContentsMargins(15, 15, 15, 15)
        self.thumbnail_scroll_area.setWidget(self.thumbnail_widget)
        content_content_layout = QVBoxLayout()
        thumbnail_header = QLabel("🖼️ Images")
        thumbnail_header.setStyleSheet(f"""
            QLabel {{
                color: {theme['foreground']};
                font-weight: bold;
                font-size: 14px;
                margin-bottom: 5px;
                qproperty-alignment: AlignCenter;
            }}
        """)
        content_content_layout.addWidget(thumbnail_header)
        content_content_layout.addWidget(self.thumbnail_scroll_area)
        content_layout.addLayout(content_content_layout, 2)

        # Initialize thumbnail selection tracking
        self.last_selected_thumbnail = None

        if DEMO_MODE:
            self.load_demo_data()
        self.refresh_lists()


    def load_demo_data(self):
        """Load demo data from demo_data.json"""
        try:
            with open("demo_data.json", "r") as f:
                data = json.load(f)
                self.demo_models = data.get("models", [])
                self.demo_projects = data.get("projects", {})
        except Exception as e:
            print(f"Error loading demo data: {e}")
            self.demo_models = []
            self.demo_projects = {}

    def closeEvent(self, event):
        """Clear undo cache when the application exits."""
        try:
            command = ["./mr_sparkru_cli.py", "--silent", "--clear-undo-cache"]
            subprocess.run(command, capture_output=True)
        except Exception:
            # Silently ignore errors during shutdown
            pass
        event.accept()  # Allow the window to close

    def refresh_lists(self):
        self.models_list.clear()
        self.projects_list.clear()

        if DEMO_MODE:
            # Load from demo data
            models = getattr(self, 'demo_models', [])
            projects = getattr(self, 'demo_projects', {})

            # Get search text and filter models
            model_search_text = self.model_search.text().lower()
            if model_search_text:
                models = [model for model in models if model_search_text in model.lower()]

            # Sort models
            sort_mode = self.model_sort_combo.currentText()
            if sort_mode == "A-Z":
                models.sort()
            elif sort_mode == "Z-A":
                models.sort(reverse=True)
            # For demo, Newest/Oldest/Largest/Smallest don't make much sense, so treat as A-Z

            for item in models:
                list_item = QListWidgetItem(item)
                self.models_list.addItem(list_item)

            # Get search text and filter projects
            project_search_text = self.project_search.text().lower()
            if project_search_text:
                projects = {name: images for name, images in projects.items() if project_search_text in name.lower()}

            # Sort projects
            project_names = list(projects.keys())
            if sort_mode == "A-Z":
                project_names.sort()
            elif sort_mode == "Z-A":
                project_names.sort(reverse=True)

            for project in project_names:
                images = projects[project]
                image_count = len(images)
                list_item = QListWidgetItem(f"{project} ({image_count} images)")
                list_item.setData(Qt.ItemDataRole.UserRole, project)
                self.projects_list.addItem(list_item)

        else:
            # Normal mode: scan filesystem
            models_path = os.path.join(self.data_path, "Documents", "Models")
            if os.path.exists(models_path):
                models = [item for item in os.listdir(models_path) if item.endswith((".ckpt", ".safetensors"))]

                # Get search text and filter
                model_search_text = self.model_search.text().lower()
                if model_search_text:
                    models = [model for model in models if model_search_text in model.lower()]

                sort_mode = self.model_sort_combo.currentText()
                if sort_mode == "A-Z":
                    models.sort()
                elif sort_mode == "Z-A":
                    models.sort(reverse=True)
                elif sort_mode == "Newest":
                    models.sort(key=lambda f: self.get_file_mtime(os.path.join(models_path, f)), reverse=True)
                elif sort_mode == "Oldest":
                    models.sort(key=lambda f: self.get_file_mtime(os.path.join(models_path, f)))
                elif sort_mode == "Largest":
                    models.sort(key=lambda f: self.get_file_size(os.path.join(models_path, f)), reverse=True)
                elif sort_mode == "Smallest":
                    models.sort(key=lambda f: self.get_file_size(os.path.join(models_path, f)))

                for item in models:
                    list_item = QListWidgetItem(item)
                    self.models_list.addItem(list_item)

            documents_path = os.path.join(self.data_path, "Documents")
            if os.path.exists(documents_path):
                projects = [os.path.splitext(item) for item in os.listdir(documents_path) if item.endswith(".sqlite3")]

                # Get search text and filter
                project_search_text = self.project_search.text().lower()
                if project_search_text:
                    projects = [(name, ext) for name, ext in projects if project_search_text in name.lower()]

                sort_mode = self.project_sort_combo.currentText()
                if sort_mode == "A-Z":
                    projects.sort()
                elif sort_mode == "Z-A":
                    projects.sort(reverse=True)
                elif sort_mode == "Newest":
                    projects.sort(key=lambda p: self.get_file_mtime(os.path.join(documents_path, f"{p[0]}.sqlite3")), reverse=True)
                elif sort_mode == "Oldest":
                    projects.sort(key=lambda p: self.get_file_mtime(os.path.join(documents_path, f"{p[0]}.sqlite3")))
                elif sort_mode == "Largest":
                    projects.sort(key=lambda p: self.get_file_size(os.path.join(documents_path, f"{p[0]}.sqlite3")), reverse=True)
                elif sort_mode == "Smallest":
                    projects.sort(key=lambda p: self.get_file_size(os.path.join(documents_path, f"{p[0]}.sqlite3")))

                for project, _ in projects:
                    db_path = os.path.join(documents_path, f"{project}.sqlite3")
                    image_count = self.get_image_count(db_path)
                    list_item = QListWidgetItem(f"{project} ({image_count} images)")
                    list_item.setData(Qt.ItemDataRole.UserRole, project)
                    self.projects_list.addItem(list_item)

        # Update button states after refresh
        self.update_button_states()

    def update_button_states(self):
        # Update models button state
        selected_models = len(self.models_list.selectedItems()) > 0
        self.delete_models_button.setEnabled(selected_models)

        # Update projects button state
        selected_projects = len(self.projects_list.selectedItems()) > 0
        self.delete_projects_button.setEnabled(selected_projects)

        # Update images button state (enabled when project is selected but disabled when no images selected)
        current_item = self.projects_list.currentItem()
        has_project_selected = current_item is not None
        selected_images = sum(1 for i in range(self.thumbnail_layout.count()) if self.thumbnail_layout.itemAt(i).widget().selected)
        self.delete_images_button.setEnabled(has_project_selected and selected_images > 0)

        # Update undo button state (enabled if undo cache exists)
        undo_available = os.path.exists(os.path.expanduser("~/.mr_sparkru_undo.json"))
        self.undo_button.setEnabled(undo_available)

        self.style_disabled_button(self.delete_models_button)
        self.style_disabled_button(self.delete_projects_button)
        self.style_disabled_button(self.delete_images_button)
        self.style_disabled_button(self.undo_button)

    def style_disabled_button(self, button):
        if not button.isEnabled():
            color = QColor(theme['button'])
            color.setHsl(color.hslHue(), color.hslSaturation(), int(color.lightness() * 0.6))
            button.setStyleSheet(f"background-color: {color.name()}; color: #888; border: 1px solid {theme['button_hover']}; border-radius: 6px; padding: 12px; text-align: center; font-weight: bold; min-width: 160px;")
        else:
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme['button']};
                    color: {theme['foreground']};
                    border: 1px solid {theme['button_hover']};
                    border-radius: 6px;
                    padding: 12px;
                    text-align: center;
                    font-weight: bold;
                    min-width: 160px;
                }}
                QPushButton:hover {{
                    background-color: {theme['button_hover']};
                    border: 1px solid {theme['text']};
                }}
                QPushButton:pressed {{
                    background-color: {theme['text']};
                }}
            """)

    def delete_selected_models(self):
        selected_items = self.models_list.selectedItems()
        selected_models = [item.text() for item in selected_items]
        
        if selected_models:
            command = ["./mr_sparkru_cli.py", "--silent", "--delete-models"] + selected_models
            subprocess.run(command, check=True)
            self.refresh_lists()
            self.start_deletion_animation()

    def delete_selected_projects(self):
        selected_items = self.projects_list.selectedItems()
        selected_projects = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]

        if selected_projects:
            command = ["./mr_sparkru_cli.py", "--silent", "--delete-projects"] + selected_projects
            subprocess.run(command, check=True)
            self.refresh_lists()
            self.clear_thumbnails()
            self.start_deletion_animation()

    def delete_selected_images(self):
        selected_images = [self.thumbnail_layout.itemAt(i).widget().property("image_id") for i in range(self.thumbnail_layout.count()) if self.thumbnail_layout.itemAt(i).widget().selected]

        if selected_images:
            current_item = self.projects_list.currentItem()
            project_name = current_item.data(Qt.ItemDataRole.UserRole)

            # Check if we're deleting the last image and prompt user
            current_image_count = self.get_image_count(os.path.join(self.data_path, "Documents", f"{project_name}.sqlite3"))
            should_delete_project = False
            if len(selected_images) >= current_image_count and current_image_count > 0:
                # Show modal dialog instead of CLI prompt
                reply = QMessageBox.question(
                    self, 'Delete Last Images',
                    f'This will delete the last image(s) from project "{project_name}".\n\nWould you also like to delete the entire project?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.Yes:
                    should_delete_project = True

            if should_delete_project:
                # Select the project in the projects list and delete it
                for i in range(self.projects_list.count()):
                    item = self.projects_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == project_name:
                        item.setSelected(True)
                        break
                self.delete_selected_projects()
            else:
                command = ["./mr_sparkru_cli.py", "--silent", "--delete-images", project_name] + [str(img_id) for img_id in selected_images]
                subprocess.run(command, check=True)
                self.display_thumbnails(current_item)  # Reselect the project
                self.refresh_lists()
                self.start_deletion_animation()

    def undo_last_action(self):
        """Undo the last deletion operation."""
        try:
            command = ["./mr_sparkru_cli.py", "--silent", "--undo"]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                # Refresh all lists and clear thumbnails after undo
                self.refresh_lists()
                self.clear_thumbnails()
        except Exception as e:
            print(f"Error running undo: {e}")

    def display_thumbnails(self, item):
        project_name = item.data(Qt.ItemDataRole.UserRole)
        self.delete_images_button.setEnabled(True)
        self.clear_thumbnails()

        if DEMO_MODE:
            # Demo mode: create placeholder thumbnails
            demo_projects = getattr(self, 'demo_projects', {})
            images = demo_projects.get(project_name, [])
            image_id = 0
            for image_name in images:
                thumbnail_widget = ClickableWidget()
                thumbnail_widget.setProperty("image_id", image_id)
                thumbnail_layout = QVBoxLayout(thumbnail_widget)

                # Create a placeholder pixmap (colored square)
                pixmap = QPixmap(128, 128)
                pixmap.fill(QColor(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255)))

                label = QLabel()
                label.setPixmap(pixmap)
                thumbnail_layout.addWidget(label)

                # Add text label for the image name
                text_label = QLabel(image_name)
                text_label.setStyleSheet(f"color: {theme['text']}; font-size: 10px;")
                text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                thumbnail_layout.addWidget(text_label)

                thumbnail_widget.clicked.connect(lambda w, e: self.toggle_image_selection(w, e))
                self.thumbnail_layout.addWidget(thumbnail_widget)
                image_id += 1
        else:
            # Normal mode: scan database
            db_path = os.path.join(self.data_path, "Documents", f"{project_name}.sqlite3")
            if VERBOSE:
                print(f"db_path: {db_path}")
            if not os.path.exists(db_path):
                return

            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()

                # Try to fetch from thumbnailhistoryhalfnode (new schema, low res)
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistoryhalfnode'")
                if cursor.fetchone():
                    cursor.execute("SELECT rowid, p FROM thumbnailhistoryhalfnode ORDER BY rowid DESC")
                    for row_id, p_blob in cursor.fetchall():
                        self.display_thumbnail_from_blob(row_id, p_blob, project_name)

                # If not found, try thumbnailhistorynode (new schema, high res)
                else:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistorynode'")
                    if cursor.fetchone():
                        cursor.execute("SELECT rowid, p FROM thumbnailhistorynode ORDER BY rowid DESC")
                        for row_id, p_blob in cursor.fetchall():
                            self.display_thumbnail_from_blob(row_id, p_blob, project_name)

                    # If not found, try ZIMAGE (old schema)
                    else:
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ZIMAGE'")
                        if cursor.fetchone():
                            cursor.execute("SELECT Z_PK, ZTHUMBNAILDATA FROM ZIMAGE WHERE ZTHUMBNAILDATA IS NOT NULL ORDER BY Z_PK DESC")
                            for row_pk, thumbnail_data in cursor.fetchall():
                                pixmap = QPixmap()
                                pixmap.loadFromData(thumbnail_data)

                                thumbnail_widget = ClickableWidget()
                                thumbnail_widget.setProperty("image_id", row_pk)
                                thumbnail_layout = QVBoxLayout(thumbnail_widget)

                                label = QLabel()
                                label.setPixmap(pixmap)
                                thumbnail_layout.addWidget(label)

                                thumbnail_widget.clicked.connect(lambda w, e: self.toggle_image_selection(w, e))
                                self.thumbnail_layout.addWidget(thumbnail_widget)

                conn.close()

            except sqlite3.Error as e:
                print(f"Database error for {project_name}: {e}")

    def clear_thumbnails(self):
        for i in reversed(range(self.thumbnail_layout.count())): 
            self.thumbnail_layout.itemAt(i).widget().setParent(None)


    def display_thumbnail_from_blob(self, image_id, blob_data, project_name):
        try:
            # Try parsing as ThumbnailHistoryHalfNode
            try:
                node = ThumbnailHistoryHalfNode.ThumbnailHistoryHalfNode.GetRootAs(blob_data)
                image_data = node.DataAsNumpy()
            except Exception:
                # Try parsing as ThumbnailHistoryNode
                node = ThumbnailHistoryNode.ThumbnailHistoryNode.GetRootAs(blob_data)
                image_data = node.DataAsNumpy()

            pixmap = QPixmap()
            pixmap.loadFromData(image_data)

            thumbnail_widget = ClickableWidget()
            thumbnail_widget.setProperty("image_id", image_id)
            thumbnail_layout = QVBoxLayout(thumbnail_widget)
            
            label = QLabel()
            label.setPixmap(pixmap.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            thumbnail_layout.addWidget(label)

            thumbnail_widget.clicked.connect(lambda w, e: self.toggle_image_selection(w, e))
            self.thumbnail_layout.addWidget(thumbnail_widget)
        except Exception as e:
            print(f"Error displaying thumbnail for {project_name}: {e}")

    def get_image_count(self, db_path):
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                cursor = conn.cursor()
                # Count thumbnails since they correspond to actual displayable images
                # Try thumbnailhistoryhalfnode first (more common)
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistoryhalfnode'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) FROM thumbnailhistoryhalfnode")
                    return cursor.fetchone()[0]
                else:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='thumbnailhistorynode'")
                    if cursor.fetchone():
                        cursor.execute("SELECT COUNT(*) FROM thumbnailhistorynode")
                        return cursor.fetchone()[0]
                    else:
                        # Fallback to old schema
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ZIMAGE'")
                        if cursor.fetchone():
                            cursor.execute("SELECT COUNT(*) FROM ZIMAGE WHERE ZTHUMBNAILDATA IS NOT NULL")
                            return cursor.fetchone()[0]
        except sqlite3.Error:
            return 0
        return 0

    def get_file_size(self, file_path):
        try:
            return os.path.getsize(file_path)
        except FileNotFoundError:
            return 0

    def get_file_mtime(self, file_path):
        try:
            return os.path.getmtime(file_path)
        except FileNotFoundError:
            return 0

    def toggle_image_selection(self, widget, event=None):
        # Check if shift is pressed for range selection
        if event and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if self.last_selected_thumbnail is not None:
                # Do range selection from last selected to current
                start_idx = self.get_thumbnail_index(self.last_selected_thumbnail)
                end_idx = self.get_thumbnail_index(widget)

                if start_idx != -1 and end_idx != -1:
                    min_idx = min(start_idx, end_idx)
                    max_idx = max(start_idx, end_idx)

                    for i in range(min_idx, max_idx + 1):
                        if i != end_idx:  # Don't toggle the current one twice
                            item_widget = self.thumbnail_layout.itemAt(i).widget()
                            item_widget.setSelected(True)

            widget.setSelected(True)  # Ensure current widget is selected
        else:
            # Clear previous selections if Control (Cmd) is not pressed
            if not (event and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)):
                for i in range(self.thumbnail_layout.count()):
                    item_widget = self.thumbnail_layout.itemAt(i).widget()
                    if item_widget != widget:
                        item_widget.setSelected(False)
            widget.setSelected(not widget.selected)

        # Update the last selected thumbnail
        if widget.selected:
            self.last_selected_thumbnail = widget
        elif not widget.selected and self.last_selected_thumbnail == widget:
            self.last_selected_thumbnail = None

        self.update_button_states()

    def get_thumbnail_index(self, widget):
        """Get the index of a thumbnail widget in the grid layout."""
        for i in range(self.thumbnail_layout.count()):
            if self.thumbnail_layout.itemAt(i).widget() == widget:
                return i
        return -1

    def set_sparkru_image(self, image_path):
        pixmap = QPixmap(os.path.join("images", image_path))
        self.sparkru_label.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
        self.current_image_path = image_path

    def start_deletion_animation(self):
        if self.animation_timer is not None:
            self.animation_timer.stop()
        # Select 3 unique random images
        animation_images = random.sample(self.sparkru_images, 3)
        self.animation_images = animation_images
        self.animation_index = 0
        # Create timer and set first image
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.next_animation_image)
        self.animation_timer.setSingleShot(False)
        # Start timer for first image at 0ms
        self.next_animation_image()
        self.animation_timer.start(333)

    def next_animation_image(self):
        if self.animation_index < len(self.animation_images):
            self.set_sparkru_image(self.animation_images[self.animation_index])
            self.animation_index += 1
        elif self.animation_index == len(self.animation_images):
            # After 3 images displayed (3 timeouts), set final random
            if self.animation_timer:
                self.animation_timer.stop()
                self.animation_timer = None
            final_image = random.choice(self.sparkru_images)
            self.set_sparkru_image(final_image)


def main():
    """Main function to run the application."""
    parser = argparse.ArgumentParser(description="Mr Sparkru - Draw Things Data Manager")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output to stdout")
    parser.add_argument("--demo-data", action="store_true", help="Load demo data from demo_data.json")
    args = parser.parse_args()

    global VERBOSE, DEMO_MODE
    VERBOSE = args.verbose
    DEMO_MODE = args.demo_data

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("./images/ms.png"))
    main_win = App()
    main_win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

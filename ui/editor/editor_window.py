import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QGraphicsView, QGraphicsScene, QToolBar,
    QColorDialog, QSpinBox, QLabel, QMessageBox, QGraphicsPixmapItem
)
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QKeySequence, QColor, QActionGroup, QAction, QUndoStack
)
from PySide6.QtCore import Qt, Signal

from ui.editor.tools import (
    RectangleTool, EllipseTool, LineTool, TextTool, ToolProperties, DeleteItemsCommand
)
from core.imaging import pil_to_qpixmap, ImageSaveWorker

class EditorView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Default mode allows selection/movement of items
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.current_tool = None
        # Access undo stack from parent window
        self.undo_stack = parent.undo_stack if parent else None

    def set_tool(self, tool):
        self.current_tool = tool
        # When drawing, disable dragging/selection
        if tool:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.scene().clearSelection()
        else:
            # Null tool means selection/move mode
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.current_tool:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.current_tool.start(self.scene(), scene_pos)
            # TextTool finishes immediately
            if isinstance(self.current_tool, TextTool):
                 self.finish_tool()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.current_tool and not isinstance(self.current_tool, TextTool):
            scene_pos = self.mapToScene(event.position().toPoint())
            self.current_tool.update(scene_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.current_tool and not isinstance(self.current_tool, TextTool):
            self.finish_tool()
        else:
            super().mouseReleaseEvent(event)

    def finish_tool(self):
         if self.current_tool:
            command = self.current_tool.end(self.scene())
            if command and self.undo_stack:
                self.undo_stack.push(command)
            # Keep the tool active for continuous drawing

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)

    def delete_selected_items(self):
        selected_items = self.scene().selectedItems()
        if selected_items and self.undo_stack:
             # Filter out the background if accidentally selected
             items_to_delete = [item for item in selected_items if not isinstance(item, QGraphicsPixmapItem)]
             if items_to_delete:
                self.undo_stack.push(DeleteItemsCommand(self.scene(), items_to_delete))


class ImageEditorWindow(QMainWindow):
    # Signal emitted when saving (passes the edited QImage)
    image_saved = Signal(QImage)

    def __init__(self, image_data: np.ndarray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("影像編輯器 (F3)")

        self.undo_stack = QUndoStack(self)
        self.tool_properties = ToolProperties()

        self.scene = QGraphicsScene(self)
        self.view = EditorView(self.scene, self)
        self.setCentralWidget(self.view)

        self.load_image(image_data)
        self.setup_toolbar()

        # Default tool: Select
        self.select_tool(None)
        self.action_select.setChecked(True)

    def load_image(self, image_data: np.ndarray):
        # Convert NumPy array (BGRA) to QImage
        height, width, channel = image_data.shape
        bytes_per_line = channel * width
        # Use Format_ARGB32_Premultiplied for efficient rendering
        q_image = QImage(image_data.data, width, height, bytes_per_line, QImage.Format.Format_ARGB32_Premultiplied)

        # We must keep a reference to the QImage or copy it, otherwise the data might be garbage collected
        self._image_ref = q_image.copy()
        pixmap = QPixmap.fromImage(self._image_ref)

        if not pixmap.isNull():
            # Background item should not be movable or selectable
            background = self.scene.addPixmap(pixmap)
            self.scene.setSceneRect(pixmap.rect().toRectF())
            self.resize(min(1200, pixmap.width() + 50), min(800, pixmap.height() + 100))
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def setup_toolbar(self):
        toolbar = QToolBar("Editor Toolbar")
        self.addToolBar(toolbar)

        # --- Tools Group ---
        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)

        self.action_select = QAction("選取/移動", self)
        self.action_select.setCheckable(True)
        self.action_select.triggered.connect(lambda: self.select_tool(None))
        tool_group.addAction(self.action_select)
        toolbar.addAction(self.action_select)

        action_rect = QAction("矩形", self)
        action_rect.setCheckable(True)
        action_rect.triggered.connect(lambda: self.select_tool(RectangleTool(self.tool_properties)))
        tool_group.addAction(action_rect)
        toolbar.addAction(action_rect)

        action_ellipse = QAction("圓形/圈選", self)
        action_ellipse.setCheckable(True)
        action_ellipse.triggered.connect(lambda: self.select_tool(EllipseTool(self.tool_properties)))
        tool_group.addAction(action_ellipse)
        toolbar.addAction(action_ellipse)

        action_line = QAction("直線/箭頭", self)
        action_line.setCheckable(True)
        action_line.triggered.connect(lambda: self.select_tool(LineTool(self.tool_properties)))
        tool_group.addAction(action_line)
        toolbar.addAction(action_line)

        action_text = QAction("文字", self)
        action_text.setCheckable(True)
        action_text.triggered.connect(lambda: self.select_tool(TextTool(self.tool_properties)))
        tool_group.addAction(action_text)
        toolbar.addAction(action_text)

        toolbar.addSeparator()

        # --- Properties ---
        self.color_indicator = QLabel("■")
        self.color_indicator.setToolTip("選擇顏色")
        self.color_indicator.mousePressEvent = self.select_color
        self.update_color_indicator()
        toolbar.addWidget(self.color_indicator)

        self.sb_size = QSpinBox()
        self.sb_size.setRange(1, 72)
        self.sb_size.setValue(3) # Default line width
        self.sb_size.valueChanged.connect(self.update_properties)
        toolbar.addWidget(QLabel("線寬/字體大小:"))
        toolbar.addWidget(self.sb_size)

        toolbar.addSeparator()

        # --- Actions ---
        action_delete = QAction("刪除選取", self)
        action_delete.setShortcut(QKeySequence.StandardKey.Delete)
        action_delete.triggered.connect(self.view.delete_selected_items)
        toolbar.addAction(action_delete)

        action_undo = self.undo_stack.createUndoAction(self, "復原")
        action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        toolbar.addAction(action_undo)

        action_redo = self.undo_stack.createRedoAction(self, "重做")
        action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        toolbar.addAction(action_redo)

        toolbar.addSeparator()

        action_save = QAction("儲存並關閉", self)
        action_save.setShortcut(QKeySequence.StandardKey.Save)
        action_save.triggered.connect(self.save_and_close)
        toolbar.addAction(action_save)

    def select_tool(self, tool_instance):
        # Update UI indicators based on the selected tool type
        if isinstance(tool_instance, TextTool):
            self.sb_size.setValue(self.tool_properties.font_size)
        elif tool_instance is not None:
            self.sb_size.setValue(self.tool_properties.line_width)

        self.view.set_tool(tool_instance)

    def select_color(self, event=None):
        color = QColorDialog.getColor(self.tool_properties.color, self)
        if color.isValid():
            self.tool_properties.color = color
            self.update_color_indicator()

    def update_color_indicator(self):
        self.color_indicator.setStyleSheet(f"color: {self.tool_properties.color.name()}; font-size: 24px; margin: 0 10px;")

    def update_properties(self, value):
        # Update both properties; the tool will use the relevant one.
        self.tool_properties.line_width = value
        self.tool_properties.font_size = value

    def save_and_close(self):
        """Renders the scene to a QImage and emits the signal."""
        self.scene.clearSelection()

        # Create QImage matching the scene size
        image = QImage(self.scene.sceneRect().size().toSize(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)

        # Render scene
        painter = QPainter(image)
        self.scene.render(painter)
        painter.end()

        self.image_saved.emit(image)
        self.undo_stack.setClean() # Mark as saved
        self.close()

    def resizeEvent(self, event):
        # Keep image aspect ratio when resizing the window
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        super().resizeEvent(event)

    def closeEvent(self, event):
        if not self.undo_stack.isClean():
             reply = QMessageBox.question(self, '關閉編輯器',
                                            "您有未儲存的變更。是否要儲存？",
                                            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
             if reply == QMessageBox.StandardButton.Save:
                 self.save_and_close()
                 # save_and_close calls close() again, so we wait for that
                 event.ignore()
             elif reply == QMessageBox.StandardButton.Discard:
                 event.accept()
             else:
                 event.ignore()
        else:
            event.accept()
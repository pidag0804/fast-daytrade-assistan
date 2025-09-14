from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsTextItem
from PySide6.QtGui import QUndoCommand, QPen, QBrush, QColor, QFont
from PySide6.QtCore import QPointF, QLineF, Qt, QRectF

# --- Tool Properties Container ---
class ToolProperties:
    def __init__(self):
        self.color = QColor(Qt.GlobalColor.red)
        self.line_width = 3
        self.font_size = 16

    def get_pen(self) -> QPen:
        return QPen(self.color, self.line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def get_font(self) -> QFont:
        # Use a common cross-platform font
        return QFont("Arial", self.font_size)

# --- Base Tool Class ---
class Tool:
    def __init__(self, properties: ToolProperties):
        self.properties = properties
        self.start_pos = QPointF()
        self.item = None

    def start(self, scene, pos):
        self.start_pos = pos

    def update(self, pos):
        pass

    def end(self, scene):
        if self.item:
            # Ensure items are movable and selectable after creation
            self.item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
            self.item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            # Return the command for the Undo stack
            return AddItemCommand(scene, self.item)
        return None

# --- Specific Tools ---

class RectangleTool(Tool):
    def start(self, scene, pos):
        super().start(scene, pos)
        self.item = QGraphicsRectItem()
        self.item.setPen(self.properties.get_pen())
        scene.addItem(self.item)

    def update(self, pos):
        if self.item:
            rect = QRectF(self.start_pos, pos).normalized()
            self.item.setRect(rect)

class EllipseTool(Tool):
    def start(self, scene, pos):
        super().start(scene, pos)
        self.item = QGraphicsEllipseItem()
        self.item.setPen(self.properties.get_pen())
        scene.addItem(self.item)

    def update(self, pos):
        if self.item:
            rect = QRectF(self.start_pos, pos).normalized()
            self.item.setRect(rect)

class LineTool(Tool):
    # MVP: Line tool serves as both line and arrow (as requested)
    def start(self, scene, pos):
        super().start(scene, pos)
        self.item = QGraphicsLineItem()
        self.item.setPen(self.properties.get_pen())
        scene.addItem(self.item)

    def update(self, pos):
        if self.item:
            self.item.setLine(QLineF(self.start_pos, pos))

class TextTool(Tool):
    def start(self, scene, pos):
        super().start(scene, pos)
        self.item = QGraphicsTextItem("請輸入文字...")
        self.item.setFont(self.properties.get_font())
        self.item.setDefaultTextColor(self.properties.color)
        self.item.setPos(pos)
        # Enable editing interaction
        self.item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        scene.addItem(self.item)
        self.item.setFocus()

    def end(self, scene):
        # Text tool finishes immediately upon creation
        if self.item:
             # If text is empty or default, remove it
             if self.item.toPlainText() == "" or self.item.toPlainText() == "請輸入文字...":
                 scene.removeItem(self.item)
                 return None
             return super().end(scene)
        return None

# --- Undo/Redo Commands ---

class AddItemCommand(QUndoCommand):
    def __init__(self, scene, item):
        super().__init__(f"Add {type(item).__name__}")
        self.scene = scene
        self.item = item
        self.initial_add = True

    def undo(self):
        self.scene.removeItem(self.item)

    def redo(self):
        # The first redo() call is actually the initial action.
        # Subsequent redo() calls restore the item if undone.
        if not self.initial_add:
             self.scene.addItem(self.item)
        self.initial_add = False

class DeleteItemsCommand(QUndoCommand):
    def __init__(self, scene, items):
        super().__init__(f"Delete {len(items)} Item(s)")
        self.scene = scene
        self.items = items # List of items

    def undo(self):
        for item in self.items:
            self.scene.addItem(item)

    def redo(self):
        for item in self.items:
            self.scene.removeItem(item)
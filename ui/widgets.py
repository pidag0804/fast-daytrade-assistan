from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QGridLayout
)
from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QGuiApplication
from core.models import AnalysisResult

# --- F4 Snipping Tool ---

class SnippingTool(QWidget):
    """A full-screen overlay for region selection (F4)."""
    # Emits monitor_dict {'left', 'top', 'width', 'height'}
    snipping_finished = Signal(dict) 

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.begin = QPoint()
        self.end = QPoint()
        self.is_snipping = False
        self.mask_color = QColor(0, 0, 0, 100)

    def start(self):
        # Cover the entire virtual desktop across all monitors
        screen_rect = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_rect)
        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.mask_color)

        if self.is_snipping:
            rect = QRect(self.begin, self.end).normalized()
            
            # Clear the selected area
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Draw border
            pen = QPen(QColor(0, 120, 215), 2) # Blue border
            painter.setPen(pen)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Use position relative to the widget (which covers the virtual desktop)
            self.begin = event.pos() 
            self.end = self.begin
            self.is_snipping = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if self.is_snipping:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_snipping:
            self.is_snipping = False
            rect = QRect(self.begin, self.end).normalized()
            
            if rect.width() > 10 and rect.height() > 10:
                # Get the virtual desktop origin to calculate absolute screen coordinates
                virtual_origin = QGuiApplication.primaryScreen().virtualGeometry().topLeft()
                
                monitor_dict = {
                    'left': virtual_origin.x() + rect.left(),
                    'top': virtual_origin.y() + rect.top(),
                    'width': rect.width(),
                    'height': rect.height()
                }
                self.hide() # Hide immediately before capture
                self.snipping_finished.emit(monitor_dict)
            
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

# --- Analysis Result Card ---

class AnalysisCard(QFrame):
    """Displays the GPT analysis result in a structured card format."""
    def __init__(self, result: AnalysisResult, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setup_ui(result)

    def setup_ui(self, result: AnalysisResult):
        layout = QGridLayout(self)

        # Title/Header
        title = QLabel(f"交易建議 (信心: {result.confidence*100:.0f}%, 風險: {result.risk_score}/5)")
        title.setObjectName("CardTitle")
        layout.addWidget(title, 0, 0, 1, 4)

        # Key Information
        bias_label = QLabel("方向:")
        bias_value = QLabel(result.bias)
        # Apply specific property for QSS styling based on bias
        bias_value.setProperty("bias", result.bias) 
        bias_value.setObjectName("CardBias")

        layout.addWidget(bias_label, 1, 0)
        layout.addWidget(bias_value, 1, 1)

        entry_label = QLabel("建議入場:")
        entry_value = QLabel(f"{result.entry_price:.2f}" if result.entry_price else "N/A")
        layout.addWidget(entry_label, 2, 0)
        layout.addWidget(entry_value, 2, 1)

        sl_label = QLabel("停損價位:")
        sl_value = QLabel(f"{result.stop_loss:.2f}" if result.stop_loss else "N/A")
        layout.addWidget(sl_label, 3, 0)
        layout.addWidget(sl_value, 3, 1)

        hold_label = QLabel("留倉短波:")
        hold_text = "是" if result.hold_overnight else ("否" if result.hold_overnight is False else "依條件")
        hold_value = QLabel(hold_text)
        layout.addWidget(hold_label, 1, 2)
        layout.addWidget(hold_value, 1, 3)

        # Rationale
        rationale_label = QLabel("分析理由:")
        layout.addWidget(rationale_label, 4, 0, 1, 4)
        rationale_text = QLabel(result.rationale)
        rationale_text.setWordWrap(True)
        layout.addWidget(rationale_text, 5, 0, 1, 4)

        # Notes (if any)
        row_index = 6
        if result.notes:
            notes_label = QLabel("備註:")
            layout.addWidget(notes_label, row_index, 0, 1, 4)
            row_index += 1
            notes_text = QLabel(result.notes)
            notes_text.setWordWrap(True)
            notes_text.setObjectName("CardNotes")
            layout.addWidget(notes_text, row_index, 0, 1, 4)
            row_index += 1

        # Metadata (Bottom right)
        if result.model_used and result.response_time:
            model_info = QLabel(f"Model: {result.model_used} | Time: {result.response_time:.2f}s")
            model_info.setObjectName("CardMeta")
            layout.addWidget(model_info, row_index, 0, 1, 4, Qt.AlignmentFlag.AlignRight)
import os
from PySide6.QtCore import QAbstractListModel, Qt, QModelIndex, QSize
from PySide6.QtGui import QImageReader, QPixmap, QIcon

THUMBNAIL_SIZE = 100

class QueueItem:
    def __init__(self, path: str):
        self.path = path
        self.filename = os.path.basename(path)
        self.thumbnail = self._create_thumbnail(path)

    def _create_thumbnail(self, path):
        """Creates a thumbnail efficiently using QImageReader."""
        try:
            # QImageReader can read metadata and scale during decoding, which is faster
            reader = QImageReader(path)
            if reader.canRead():
                original_size = reader.size()
                if original_size.isValid():
                    scaled_size = original_size.scaled(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE), Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(scaled_size)
                
                image = reader.read()
                if not image.isNull():
                    return QPixmap.fromImage(image)
            
            # Fallback
            return QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE).fill(Qt.GlobalColor.lightGray)
        except Exception as e:
            print(f"Error creating thumbnail for {path}: {e}")
            return QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE).fill(Qt.GlobalColor.red)

class UploadQueueModel(QAbstractListModel):
    PathRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue: list[QueueItem] = []

    def rowCount(self, parent=QModelIndex()):
        return len(self.queue)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.queue):
            return None

        item = self.queue[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        if role == Qt.ItemDataRole.DecorationRole:
            # Use QIcon for better display in ListView IconMode
            return QIcon(item.thumbnail)
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.path
        if role == self.PathRole:
            return item.path

    def add_item(self, path: str):
        # Insert at the beginning (newest first)
        self.beginInsertRows(QModelIndex(), 0, 0)
        self.queue.insert(0, QueueItem(path))
        self.endInsertRows()

    def remove_items(self, indexes: list[QModelIndex]):
        # Sort rows descending to avoid index shifting during removal
        rows = sorted([index.row() for index in indexes], reverse=True)
        for row in rows:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.queue[row]
            self.endRemoveRows()

    def clear_queue(self):
        self.beginResetModel()
        self.queue = []
        self.endResetModel()

    def get_paths_by_indexes(self, indexes: list[QModelIndex]) -> list[str]:
        """Returns paths corresponding to the given indexes, sorted by their visual order."""
        if not indexes:
            return []
             
        # Sort indexes by row number to ensure the order matches the visual list
        rows = sorted([index.row() for index in indexes])
        return [self.queue[row].path for row in rows]

    # --- Drag and Drop Support (Internal Move) ---
    def flags(self, index):
        flags = super().flags(index)
        if index.isValid():
            return flags | Qt.ItemFlag.ItemIsDragEnabled
        return flags | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        if sourceRow < 0 or destinationChild < 0 or sourceRow >= len(self.queue) or destinationChild > len(self.queue):
             return False

        # Prevent moving an item onto itself
        if destinationChild >= sourceRow and destinationChild < sourceRow + count:
            return False

        self.beginMoveRows(sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild)

        # Extract items to move
        items_to_move = self.queue[sourceRow:sourceRow + count]
        
        # Remove from source
        for i in range(count):
            self.queue.pop(sourceRow)

        # Adjust insertion index if moving downwards
        insertion_index = destinationChild
        if destinationChild > sourceRow:
            insertion_index -= count

        # Insert at destination
        for i in range(count):
            self.queue.insert(insertion_index + i, items_to_move[i])

        self.endMoveRows()
        return True
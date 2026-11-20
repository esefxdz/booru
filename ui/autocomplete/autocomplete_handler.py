from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt6.QtGui import QColor
import ui.animations as anims
from ui.autocomplete.tag_complete_thread import TagCompleteWorker
from PyQt6.QtCore import QThreadPool

class AutocompleteHandlerSignals(QObject):
    # Fires True when the dropdown appears, False when it disappears
    visibility_changed = pyqtSignal(bool)


from ui.style import colors

class AutocompleteHandler:

    def __init__(self, entry_widget, list_widget, central_widget):
        self.signals = AutocompleteHandlerSignals()
        self.entry = entry_widget
        self.ac_list = list_widget
        self.central = central_widget
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._trigger)
        self._worker = None

        self.entry.textChanged.connect(self._on_text_changed)
        self.ac_list.itemClicked.connect(self._on_selected)

    def _on_text_changed(self, text):
        if not text.strip() or text.endswith(" "):
            if self.ac_list.isVisible():
                self.ac_list.hide()
                self.signals.visibility_changed.emit(False)
            self._timer.stop()
            return

        last = text.split()[-1] if text.strip() else ""
        if len(last) >= 2:
            self._timer.start(250)
        else:
            self.ac_list.hide()
            self._timer.stop()

    def _trigger(self):
        text = self.entry.text()
        last = text.split()[-1] if text.strip() else ""
        if len(last) < 2:
            return

        if self._worker:
            self._worker.cancel()

        self._worker = TagCompleteWorker(last)
        self._worker.signals.results_ready.connect(self._show)
        QThreadPool.globalInstance().start(self._worker)

    def _show(self, results):
        if results is not None:
            if self.ac_list.count() > 0 and self.ac_list.isVisible():
                new_names = {tag.get("name", "") for tag in results[:15]}
                old_names = {
                    self.ac_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.ac_list.count())
                }
                if new_names == old_names:
                    return

            self.ac_list.clear()
            if not results:
                self.ac_list.hide()
                self.signals.visibility_changed.emit(False)
                return

            TYPE_COLORS = {
                "artist":    colors.AC_TAG_ARTIST,
                "copyright": colors.AC_TAG_COPYRIGHT,
                "character": colors.AC_TAG_CHARACTER,
                "meta":      colors.AC_TAG_METADATA,
                "general":   colors.TAG_GENERAL,
            }
            for tag in results[:15]:  # Cap at 15 items to keep the list manageable
                name  = tag.get("name", "")
                ttype = tag.get("type", "general")
                count = tag.get("count", 0)
                item = QListWidgetItem(f"{name}  ({ttype} · {count:,})")
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setForeground(QColor(TYPE_COLORS.get(ttype, colors.TAG_GENERAL)))
                self.ac_list.addItem(item)
            self._last_count = len(results)

        scale = self.ac_list.logicalDpiY() / 96.0
        row_h = int(38 * scale)
        pos = self.entry.mapTo(self.central, QPoint(0, self.entry.height() + 5))
        self.ac_list.setGeometry(
            pos.x(), pos.y(),
            self.entry.width(),
            min(getattr(self, '_last_count', 0), 10) * row_h + 2
        )

        if not self.ac_list.isVisible():
            self.ac_list.show()
            anims.animate_fade_in(self.ac_list, duration=200)
            self.signals.visibility_changed.emit(True)

        self.ac_list.raise_()
        self.ac_list.setCurrentRow(0)

    def _on_selected(self, item):
        tag_name = item.data(Qt.ItemDataRole.UserRole)
        cur = self.entry.text()
        parts = cur.split()
        if parts:
            parts[-1] = tag_name
        else:
            parts = [tag_name]
        self.entry.setText(" ".join(parts) + " ")
        self.ac_list.hide()
        self.signals.visibility_changed.emit(False)
        self.entry.setFocus()

    def handle_key(self, event):
        if not self.ac_list.isVisible():
            return False

        if event.key() == Qt.Key.Key_Down:
            row = self.ac_list.currentRow()
            if row < self.ac_list.count() - 1:
                self.ac_list.setCurrentRow(row + 1)
            return True
        elif event.key() == Qt.Key.Key_Up:
            row = self.ac_list.currentRow()
            if row > 0:
                self.ac_list.setCurrentRow(row - 1)
            elif row == 0:
                self.ac_list.setCurrentRow(-1)
            return True
        elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
            item = self.ac_list.currentItem()
            if item:
                self._on_selected(item)
                return True
        elif event.key() == Qt.Key.Key_Escape:
            self.ac_list.hide()
            return True
        return False

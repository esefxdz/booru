from PyQt6.QtWidgets import QListWidgetItem
from PyQt6.QtCore import Qt, QTimer, QPoint, QObject, pyqtSignal
from PyQt6.QtGui import QColor
import ui.animations as anims
from ui.autocomplete.tag_complete_thread import TagCompleteWorker
from PyQt6.QtCore import QThreadPool

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: AutocompleteHandlerSignals                                  ║
# ║  A tiny QObject just to provide a proper Qt signal for the         ║
# ║  non-QObject AutocompleteHandler class to emit.                    ║
# ╚══════════════════════════════════════════════════════════════════════╝
class AutocompleteHandlerSignals(QObject):
    # Fires True when the dropdown appears, False when it disappears
    visibility_changed = pyqtSignal(bool)


from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: AutocompleteHandler                                         ║
# ║  Orchestrates the whole autocomplete flow: debounces keystrokes,   ║
# ║  spawns TagCompleteThread, populates the list, handles keyboard    ║
# ║  navigation, and completes the selected tag back into the input.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class AutocompleteHandler:

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — connects the entry widget's text changes and the   │
    # │  list's item clicks, then sets up a 250ms debounce timer so we  │
    # │  don't fire a network request on every single keystroke         │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, entry_widget, list_widget, central_widget):
        self.signals = AutocompleteHandlerSignals()
        self.entry = entry_widget       # The QLineEdit the user is typing into
        self.ac_list = list_widget      # The AutocompleteList floating widget
        self.central = central_widget   # Parent widget used for coordinate mapping
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._trigger)
        self._worker = None             # Holds the running TagCompleteWorker

        self.entry.textChanged.connect(self._on_text_changed)
        self.ac_list.itemClicked.connect(self._on_selected)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_text_changed  — immediately hides the list if the input is │
    # │  empty or ends with a space (user just finished a tag and is    │
    # │  starting a new one). Otherwise starts or resets the debounce  │
    # │  timer — only query once the user pauses typing for 250ms.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_text_changed(self, text):
        if not text.strip() or text.endswith(" "):
            if self.ac_list.isVisible():
                self.ac_list.hide()
                self.signals.visibility_changed.emit(False)
            self._timer.stop()
            return

        # Only autocomplete the last word being typed (after any spaces)
        last = text.split()[-1] if text.strip() else ""
        if len(last) >= 2:
            self._timer.start(250)  # Wait 250ms before firing the network request
        else:
            # Too short to show useful results — hide the list
            self.ac_list.hide()
            self._timer.stop()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _trigger  — called when the debounce timer fires. Kills any    │
    # │  still-running thread (user kept typing) then starts a fresh    │
    # │  TagCompleteThread for the current last word.                   │
    # └──────────────────────────────────────────────────────────────────┘
    def _trigger(self):
        text = self.entry.text()
        last = text.split()[-1] if text.strip() else ""
        if len(last) < 2:
            return

        # Cancel the previous worker if the user typed faster than our timeout
        if self._worker:
            self._worker.cancel()

        self._worker = TagCompleteWorker(last)
        self._worker.signals.results_ready.connect(self._show)
        QThreadPool.globalInstance().start(self._worker)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _show  — receives the result list from the background thread,  │
    # │  colours each item by tag type, sizes the dropdown to fit, and  │
    # │  animates it into view. Passing None re-positions without       │
    # │  clearing the list (used on window resize).                     │
    # └──────────────────────────────────────────────────────────────────┘
    def _show(self, results):
        if results is not None:
            # Skip if the list already shows identical results
            # (cache emitted first, network returned same data)
            if self.ac_list.count() > 0 and self.ac_list.isVisible():
                new_names = {tag.get("name", "") for tag in results[:15]}
                old_names = {
                    self.ac_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.ac_list.count())
                }
                if new_names == old_names:
                    return  # no change — don't flicker

            self.ac_list.clear()
            if not results:
                self.ac_list.hide()
                self.signals.visibility_changed.emit(False)
                return

            # Each tag type gets its own colour so artists/characters are
            # visually distinguishable at a glance
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
                # Store the raw name in UserRole so we can retrieve it without parsing
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setForeground(QColor(TYPE_COLORS.get(ttype, colors.TAG_GENERAL)))
                self.ac_list.addItem(item)
            self._last_count = len(results)

        # Position the dropdown directly below the search input in window coords
        scale = self.ac_list.logicalDpiY() / 96.0
        row_h = int(38 * scale)  # Taller rows scaled by DPI
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

        self.ac_list.raise_()         # Float above all other widgets
        self.ac_list.setCurrentRow(0) # Pre-select the first result so Tab completes it

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_selected  — replaces the last word in the input with the   │
    # │  chosen tag name, adds a trailing space ready for the next tag, │
    # │  hides the dropdown, and returns focus to the input field       │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_selected(self, item):
        tag_name = item.data(Qt.ItemDataRole.UserRole)
        cur = self.entry.text()
        parts = cur.split()
        if parts:
            parts[-1] = tag_name  # Replace the partial word with the full tag
        else:
            parts = [tag_name]
        self.entry.setText(" ".join(parts) + " ")  # Trailing space starts next tag
        self.ac_list.hide()
        self.signals.visibility_changed.emit(False)
        self.entry.setFocus()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  handle_key  — intercepts arrow keys, Enter/Tab, and Escape     │
    # │  from the search input while the dropdown is visible, so the    │
    # │  user can navigate and select without leaving the keyboard.     │
    # │  Returns True if the event was consumed, False to pass it on.   │
    # └──────────────────────────────────────────────────────────────────┘
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
                # Pressing Up at the top deselects everything (focus is implicit)
                self.ac_list.setCurrentRow(-1)
            return True
        elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
            item = self.ac_list.currentItem()
            if item:
                self._on_selected(item)
                return True
        elif event.key() == Qt.Key.Key_Escape:
            # Dismiss the dropdown without selecting anything
            self.ac_list.hide()
            return True
        return False

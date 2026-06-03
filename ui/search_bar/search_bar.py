from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QScrollArea, QFrame, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from ui.icons import Icons
from ui.search_bar.search_tag_chip import SearchTagChip
from ui.autocomplete import AutocompleteList, AutocompleteHandler

from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                        CLASS: BooruSearchBar                        ║
# ║  The main search input. Instead of a plain text box, it shows a     ║
# ║  row of interactive 'chips' for active tags, followed by a text     ║
# ║  input for typing new ones. Integrates fully with Autocomplete.    ║
# ╚══════════════════════════════════════════════════════════════════════╝
class BooruSearchBar(QFrame):
    # Emits the full search string (e.g. "solo -rating:explicit") when Enter is pressed
    search_triggered = pyqtSignal(str)
    # Compatibility alias for BooruGui
    searchTriggered = search_triggered

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — builds the chip-container (scrollable) and the     │
    # │  text input. Initialises the AutocompleteHandler to watch the   │
    # │  input field.                                                   │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.setObjectName("SearchBar")
        self.setStyleSheet(f"""
            #SearchBar {{
                background-color: {colors.INPUT_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                padding: 4px 8px;
            }}
            #SearchBar:focus-within {{
                border: 1px solid {colors.ACCENT};
            }}
        """)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 0, 5, 0)
        self.layout.setSpacing(5)
        
        # ── Chip Container (Scrollable) ────────────────────────────────
        # If the user has 50 tags, they should scroll horizontally, not wrap
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        self.chip_container = QWidget()
        self.chip_container.setStyleSheet("background: transparent;")
        self.chip_layout = QHBoxLayout(self.chip_container)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(6)
        
        self.scroll.setWidget(self.chip_container)
        self.layout.addWidget(self.scroll, 1) # Give it all available stretch
        
        # ── Text Input ─────────────────────────────────────────────────
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Search tags...")
        self.entry.setMinimumWidth(150)
        self.entry.setStyleSheet(f"background: transparent; border: none; color: {colors.TEXT_PRIMARY}; padding: 8px 0;")
        self.entry.returnPressed.connect(self._on_return)
        self.entry.installEventFilter(self)
        self.chip_layout.addWidget(self.entry)
        
        # ── Autocomplete ───────────────────────────────────────────────
        self.ac_list = AutocompleteList(self.parent_gui)
        self.ac_handler = AutocompleteHandler(self.entry, self.ac_list, self.parent_gui)
        # Shift the text input focus manually when the dropdown disappears
        self.ac_handler.signals.visibility_changed.connect(lambda visible: None)
        
        # Compatibility aliases for BooruGui
        self.input = self.entry

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  text  — compatibility alias for BooruGui                        │
    # └──────────────────────────────────────────────────────────────────┘
    def text(self) -> str:
        return self.get_tags()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  get_tags  — parses the entry text and current chips to return   │
    # └──────────────────────────────────────────────────────────────────┘
    def get_tags(self) -> str:
        chips = []
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, SearchTagChip):
                prefix = "-" if w.is_neg else ""
                chips.append(prefix + w.tag)
        
        # Add whatever the user is currently typing in the text field
        txt = self.entry.text().strip()
        if txt:
            chips.append(txt)
        return " ".join(chips)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  setText  — compatibility alias for BooruGui                     │
    # └──────────────────────────────────────────────────────────────────┘
    def setText(self, query: str):
        self.set_tags(query)

    def set_tags(self, query: str):
        """Clears existing chips and rebuilds them from the query string."""
        # Clean out old chips (keep the entry widget!)
        while self.chip_layout.count() > 1:
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        for part in query.split():
            if not part.strip(): continue
            chip = SearchTagChip(part)
            chip.removed.connect(self._remove_tag)
            # Insert before the entry widget
            self.chip_layout.insertWidget(self.chip_layout.count() - 1, chip)
        
        self.entry.clear()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  add_tag_chip  — compatibility method for BooruGui               │
    # └──────────────────────────────────────────────────────────────────┘
    def add_tag_chip(self, tag: str):
        """Adds a single tag chip without clearing existing ones."""
        chip = SearchTagChip(tag)
        chip.removed.connect(self._remove_tag)
        self.chip_layout.insertWidget(self.chip_layout.count() - 1, chip)

    def _remove_tag(self, tag_name):
        """Finds and immediately removes the chip for a specific tag name.

        Using only deleteLater() without first removing from the layout is
        a bug: the chip stays in the layout until the Qt event loop runs, so
        if a search fires in the same frame the tag still appears in get_tags().
        Calling removeWidget() first makes the removal instant and synchronous.
        """
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, SearchTagChip) and w.tag == tag_name:
                self.chip_layout.removeWidget(w)  # Removes from layout immediately
                w.deleteLater()                    # Schedules Qt memory release
                # Trigger a fresh search so the gallery updates instantly
                self.search_triggered.emit(self.get_tags())
                break

    def _on_return(self):
        """Called when user presses Enter.

        If there is text in the input box, it is first converted to a chip.
        Then a search is always triggered, so one Enter press is all it takes
        regardless of whether the user typed something or not.
        """
        txt = self.entry.text().strip()
        if txt:
            # Convert the typed text to a chip so it appears in the chip row
            self.set_tags(self.get_tags())
        # Always fire the search — chips OR empty means "search now"
        self.search_triggered.emit(self.get_tags())

    def eventFilter(self, obj, event):
        """Intercepts keystrokes from the QLineEdit before it processes them."""
        if obj == self.entry and event.type() == event.Type.KeyPress:
            # 1. Let Autocomplete try to handle arrow keys or Enter/Tab
            if self.ac_handler.handle_key(event):
                return True
            
            # 2. Handle backspace to delete the last chip.
            #    We call removeWidget() immediately (not just deleteLater) so
            #    that rapid backspaces each see the updated layout count and
            #    can't accidentally target the entry widget itself.
            if event.key() == Qt.Key.Key_Backspace and not self.entry.text():
                # count()-1 is the entry widget itself; count()-2 is the last chip
                if self.chip_layout.count() > 1:
                    last_chip_idx = self.chip_layout.count() - 2
                    w = self.chip_layout.itemAt(last_chip_idx).widget()
                    if w and isinstance(w, SearchTagChip):
                        self.chip_layout.removeWidget(w)  # Immediate — safe for rapid keypresses
                        w.deleteLater()
                return True
                
        return super().eventFilter(obj, event)

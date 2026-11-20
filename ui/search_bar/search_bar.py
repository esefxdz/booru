from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QScrollArea, QFrame
from PyQt6.QtCore import Qt, pyqtSignal
from ui.search_bar.search_tag_chip import SearchTagChip
from ui.autocomplete import AutocompleteList, AutocompleteHandler

from ui.style import colors

class BooruSearchBar(QFrame):
    # Emits the full search string (e.g. "solo -rating:explicit") when Enter is pressed
    search_triggered = pyqtSignal(str)
    searchTriggered = search_triggered

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
        
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(5, 0, 5, 0)
        self._main_layout.setSpacing(5)
        
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
        self._main_layout.addWidget(self.scroll, 1)
        
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Search tags...")
        self.entry.setMinimumWidth(150)
        self.entry.setStyleSheet(f"background: transparent; border: none; color: {colors.TEXT_PRIMARY}; padding: 8px 0;")
        self.entry.returnPressed.connect(self._on_return)
        self.entry.installEventFilter(self)
        self.chip_layout.addWidget(self.entry)
        
        self.ac_list = AutocompleteList(self.parent_gui)
        self.ac_handler = AutocompleteHandler(self.entry, self.ac_list, self.parent_gui)
        self.ac_handler.signals.visibility_changed.connect(lambda visible: None)
        
        self.input = self.entry

    def text(self) -> str:
        return self.get_tags()

    def get_tags(self) -> str:
        chips = []
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, SearchTagChip):
                prefix = "-" if w.is_neg else ""
                chips.append(prefix + w.tag)
        
        txt = self.entry.text().strip()
        if txt:
            chips.append(txt)
        return " ".join(chips)

    def setText(self, query: str):
        self.set_tags(query)

    def set_tags(self, query: str):
        while self.chip_layout.count() > 1:
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        for part in query.split():
            if not part.strip():
                continue
            chip = SearchTagChip(part)
            chip.removed.connect(self._remove_tag)
            self.chip_layout.insertWidget(self.chip_layout.count() - 1, chip)
        
        self.entry.clear()

    def add_tag_chip(self, tag: str):
        chip = SearchTagChip(tag)
        chip.removed.connect(self._remove_tag)
        self.chip_layout.insertWidget(self.chip_layout.count() - 1, chip)

    def _remove_tag(self, tag_name):
        """Remove the chip from the layout at once; deleteLater alone leaves it in get_tags()."""
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, SearchTagChip) and w.tag == tag_name:
                self.chip_layout.removeWidget(w)
                w.deleteLater()
                self.search_triggered.emit(self.get_tags())
                break

    def _on_return(self):
        """Turn any typed text into a chip, then always search."""
        txt = self.entry.text().strip()
        if txt:
            self.set_tags(self.get_tags())
        self.search_triggered.emit(self.get_tags())

    def eventFilter(self, obj, event):
        if obj == self.entry and event.type() == event.Type.KeyPress:
            if self.ac_handler.handle_key(event):
                return True
            
            # Remove the chip immediately (not just deleteLater) so rapid backspaces see the updated layout.
            if event.key() == Qt.Key.Key_Backspace and not self.entry.text():
                # count()-1 is the entry widget itself; count()-2 is the last chip
                if self.chip_layout.count() > 1:
                    last_chip_idx = self.chip_layout.count() - 2
                    w = self.chip_layout.itemAt(last_chip_idx).widget()
                    if w and isinstance(w, SearchTagChip):
                        self.chip_layout.removeWidget(w)
                        w.deleteLater()
                return True
                
        return super().eventFilter(obj, event)

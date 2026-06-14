"""
displayers/comments.py — REMOVED.

The comments feature was non-functional and has been removed for the alpha
release.  This stub exists so existing imports don't crash; the class is a
no-op QWidget that hides itself immediately.
"""
from PyQt6.QtWidgets import QWidget


class CommentsSection(QWidget):
    """No-op stub — comments feature removed."""
    def __init__(self, sidebar=None):
        super().__init__()
        self.hide()

    def load_post(self, post):
        pass

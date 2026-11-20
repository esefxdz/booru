"""main._setup_logging must never stop startup, even if data_dir() raises.

main.py runs app-wide side effects on import, so the function is extracted
from its source and exec'd in isolation.
"""
import ast
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core import app_paths

MAIN = Path(__file__).resolve().parent.parent / "main.py"


def _load_setup_logging():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_setup_logging")
    ns = {"logging": logging, "sys": sys, "RotatingFileHandler": RotatingFileHandler,
          "traceback": __import__("traceback")}
    exec(compile(ast.Module([fn], []), str(MAIN), "exec"), ns)
    return ns["_setup_logging"]


def test_setup_logging_survives_data_dir_failure(monkeypatch):
    def boom():
        raise PermissionError("LOCALAPPDATA not writable")

    captured = {}
    monkeypatch.setattr(app_paths, "data_dir", boom)
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: captured.update(kw))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored afterwards

    _load_setup_logging()()  # must not raise

    assert not any(isinstance(h, RotatingFileHandler) for h in captured["handlers"])
    assert any(isinstance(h, logging.StreamHandler) for h in captured["handlers"])


def test_error_dialog_is_built_on_the_gui_thread(monkeypatch):
    """The excepthook may fire on a worker thread (PyQt routes slot/QThread
    exceptions there); the dialog must still be created on the GUI thread."""
    import threading
    from PyQt6.QtWidgets import QApplication

    # A full QApplication (not QCoreApplication): later tests reuse the
    # instance to build widgets, which crashes on a bare QCoreApplication.
    app = QApplication.instance() or QApplication([])
    built_on = []

    class FakeBox:
        class Icon:
            Critical = 0

        def __init__(self):
            built_on.append(threading.current_thread())

        def setIcon(self, *a): pass
        def setWindowTitle(self, *a): pass
        def setText(self, *a): pass
        def setDetailedText(self, *a): pass
        def exec(self): pass

    class FakeApp:
        @staticmethod
        def instance():
            return app

    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_setup_logging")
    ns = {"logging": logging, "sys": sys, "RotatingFileHandler": RotatingFileHandler,
          "traceback": __import__("traceback"), "QApplication": FakeApp,
          "QMessageBox": FakeBox}
    exec(compile(ast.Module([fn], []), str(MAIN), "exec"), ns)
    monkeypatch.setattr(app_paths, "data_dir", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    ns["_setup_logging"]()
    hook = sys.excepthook

    def worker():
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            hook(*sys.exc_info())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    app.processEvents()
    assert built_on == [threading.main_thread()]

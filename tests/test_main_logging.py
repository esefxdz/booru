"""main._setup_logging must never stop startup, even if data_dir() raises.

main.py runs app-wide side effects on import, so the function is extracted
from its source and exec'd in isolation.
"""
import ast
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import app_paths

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

"""Removing the active booru with no fallback must land on a real built-in."""
import ast
from pathlib import Path
from types import SimpleNamespace

import boorus

GUI = Path(__file__).resolve().parent.parent / "gui.py"


def _remove_booru_fn():
    tree = ast.parse(GUI.read_text(encoding="utf-8"))
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for n in cls.body:
            if isinstance(n, ast.FunctionDef) and n.name == "remove_booru":
                return n
    raise AssertionError("remove_booru not found")


def test_fallback_is_a_registered_booru(monkeypatch):
    mgr = SimpleNamespace(booru_order=[], active_booru="gone", save=lambda: None)
    ns = {"settings": SimpleNamespace(manager=mgr),
          "boorus": SimpleNamespace(remove_booru=lambda name: None)}
    fn = _remove_booru_fn()
    exec(compile(ast.Module([fn], []), str(GUI), "exec"), ns)
    noop = lambda: None  # noqa: E731
    me = SimpleNamespace(
        server_bar=SimpleNamespace(rebuild_list=noop, update_button_styles=noop),
        sidebar=SimpleNamespace(update_active_booru=noop),
        **{k: noop for k in ("load_active_booru",)})
    try:
        ns["remove_booru"](me, "gone")
    except AttributeError:
        pass  # later UI calls are irrelevant; active_booru is already set
    assert mgr.active_booru in boorus.REGISTRY

"""The legacy viewer runs in the main process (0cb2481), so its worker threads
must never touch widgets directly, and a worker that finishes after the
window was closed (WA_DeleteOnClose) must not raise."""
import threading

import pytest

_REAL_LOAD_IMAGE = None


@pytest.fixture
def lw_env(monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication
    from displayers import legacy_window as lw
    from core import settings

    global _REAL_LOAD_IMAGE
    _REAL_LOAD_IMAGE = lw.DisplayerWindow._load_image
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(lw.DisplayerWindow, "_load_image", lambda self, optimized: None)
    monkeypatch.setattr(settings.manager, "get_download_dir", lambda: tmp_path)

    gate = threading.Event()
    state = {"fail": False}

    def fake_fetch(url, booru_name=None):
        assert gate.wait(5)
        if state["fail"]:
            raise OSError("boom")
        return b"data"

    monkeypatch.setattr(lw, "_fetch_bytes", fake_fetch)

    threads = []
    real_thread = threading.Thread

    def recording_thread(*a, **k):
        t = real_thread(*a, **k)
        threads.append(t)
        return t

    monkeypatch.setattr(lw.threading, "Thread", recording_thread)

    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))

    def make_window():
        return lw.DisplayerWindow({"id": 7, "_booru": "safebooru"},
                                  "https://safebooru.org/images/1/x.png")

    return app, make_window, gate, state, threads, errors


def _join(threads):
    for t in threads:
        t.join(5)
        assert not t.is_alive()


@pytest.mark.parametrize("fail, expected", [(False, "Downloaded"), (True, "Failed")])
def test_download_result_is_applied_on_the_gui_thread(lw_env, fail, expected):
    app, make_window, gate, state, threads, errors = lw_env
    state["fail"] = fail
    w = make_window()
    w._download()
    assert w.dl_btn.text() == "Downloading..."
    gate.set()
    _join(threads)
    # The worker only queued the update; the widget has not been touched yet.
    assert w.dl_btn.text() == "Downloading..."
    app.processEvents()
    assert w.dl_btn.text() == expected
    assert errors == []
    w.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("fail", [False, True])
def test_download_finishing_after_window_deleted_does_not_raise(lw_env, fail):
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    app, make_window, gate, state, threads, errors = lw_env
    state["fail"] = fail
    w = make_window()
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    w._download()
    w.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert sip.isdeleted(w), "window must really be deleted before the worker ends"
    gate.set()
    _join(threads)
    app.processEvents()
    assert errors == []


def test_image_worker_after_window_deleted_is_dropped_quietly(lw_env, monkeypatch):
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    from displayers import legacy_window as lw
    app, make_window, gate, state, threads, errors = lw_env
    w = make_window()
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    logged = []
    monkeypatch.setattr(lw.logging, "error", lambda msg, *a, **k: logged.append(msg))
    _REAL_LOAD_IMAGE(w, True)
    w.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert sip.isdeleted(w)
    gate.set()
    _join(threads)
    app.processEvents()
    assert errors == []
    assert logged == [], "a closed window is not an image load error"


def test_close_stops_the_video_player(lw_env):
    app, make_window, gate, state, threads, errors = lw_env
    calls = []

    class _FakePlayer:                    # plain object: no multimedia backend needed
        def stop(self):
            calls.append("stop")

        def setSource(self, url):
            calls.append(("source", url.isEmpty()))

    w = make_window()
    w.player = _FakePlayer()
    w.close()
    assert calls == ["stop", ("source", True)]
    w.deleteLater()
    app.processEvents()


def test_gif_worker_after_window_deleted_is_dropped_quietly(lw_env, monkeypatch):
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    from displayers import legacy_window as lw
    app, make_window, gate, state, threads, errors = lw_env
    w = make_window()
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    logged = []
    monkeypatch.setattr(lw.logging, "error", lambda msg, *a, **k: logged.append(msg))
    w._load_gif(True)
    w.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert sip.isdeleted(w)
    gate.set()
    _join(threads)
    app.processEvents()
    assert errors == []
    assert logged == [], "a closed window is not a GIF load error"

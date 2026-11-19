import threading

from fileutil import atomic_write_text


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    p = tmp_path / "x.json"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text() == "two"
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_concurrent_writers_never_corrupt(tmp_path):
    p = tmp_path / "x.json"
    payloads = [("A" * 5000), ("B" * 5000), ("C" * 5000)]
    errors = []

    def w(s):
        for _ in range(40):
            try:
                atomic_write_text(p, s)
            except OSError as e:
                errors.append(e)

    ts = [threading.Thread(target=w, args=(s,)) for s in payloads]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert p.read_text() in payloads          # always one complete payload
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]

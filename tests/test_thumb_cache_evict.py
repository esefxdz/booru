"""L2 thumbnail cache only runs its eviction scan every N writes."""
import thumb_cache


def test_eviction_scan_runs_once_per_batch_of_puts(tmp_path):
    l2 = thumb_cache._L2(tmp_path / "t.db", max_bytes=10_000_000)
    calls = []
    real = l2._maybe_evict
    l2._maybe_evict = lambda conn: (calls.append(1), real(conn))[1]
    for i in range(250):
        l2.put(f"k{i}", b"x" * 10)
    assert len(calls) == 2


def test_eviction_still_trims_when_over_budget(tmp_path):
    l2 = thumb_cache._L2(tmp_path / "t.db", max_bytes=500)
    for i in range(100):
        l2.put(f"k{i}", b"x" * 100)
    conn = l2._ensure_conn()
    assert conn.execute("SELECT COUNT(*) FROM thumbs").fetchone()[0] < 100

"""async_runner must deliver every callback, even with many jobs in flight."""
from __future__ import annotations

import gc
import time

from app.core.async_runner import async_runner


def test_concurrent_jobs_all_call_back(qtbot):
    # Regression: the per-job signals object was only referenced locally, so
    # GC could collect it mid-job and its done() callback was silently lost.
    n = 20
    got: list[int] = []

    def job(i: int):
        def run() -> int:
            time.sleep(0.05 + 0.005 * i)
            return i
        return run

    for i in range(n):
        async_runner.run(job(i), got.append)
    gc.collect()
    qtbot.waitUntil(lambda: len(got) == n, timeout=5000)
    assert sorted(got) == list(range(n))
    qtbot.waitUntil(lambda: not async_runner._inflight, timeout=1000)


def test_error_callback_delivered(qtbot):
    errors: list[Exception] = []

    def boom() -> None:
        raise ValueError("nope")

    async_runner.run(boom, lambda _r: None, errors.append)
    gc.collect()
    qtbot.waitUntil(lambda: len(errors) == 1, timeout=3000)
    assert isinstance(errors[0], ValueError)

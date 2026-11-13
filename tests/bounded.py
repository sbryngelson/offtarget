"""A bounded thread-pool map for the checker sample tests."""
import queue
import threading
import time

import pytest

# Two Tioga suite runs hung in the AFAR-backed sample
# checks (test_fuzz::test_sample_passes_the_three_checks,
# test_fuzz_base::test_derived_sample_passes_every_check). Each checker
# call has its own subprocess timeout (offload.engine.fuzz, flang_oracle,
# expected.run_elided); the sample as a whole also has a budget, so a
# hang fails the test instead of blocking the suite.
SAMPLE_BUDGET_S = 600


def bounded_map(fn, items, workers: int = 16,
                budget_s: float = SAMPLE_BUDGET_S) -> list:
    """[fn(x) for x in items] on `workers` daemon threads; pytest.fail
    when the calls have not all finished within `budget_s` seconds. The
    threads are daemons, so a call that never returns cannot block the
    interpreter's exit either; the queued calls are dropped."""
    items = list(items)
    out = [None] * len(items)
    errs = []
    todo = queue.Queue()
    for k in range(len(items)):
        todo.put(k)
    done = threading.Semaphore(0)
    stop = threading.Event()

    def work():
        while not stop.is_set():
            try:
                k = todo.get_nowait()
            except queue.Empty:
                return
            try:
                out[k] = fn(items[k])
            except BaseException as e:        # re-raised in the caller
                errs.append(e)
            done.release()

    for _ in range(min(workers, len(items))):
        threading.Thread(target=work, daemon=True).start()
    deadline = time.monotonic() + budget_s
    for n in range(len(items)):
        if not done.acquire(timeout=max(0.0, deadline - time.monotonic())):
            stop.set()
            pytest.fail(f"{len(items) - n} of {len(items)} checker calls "
                        f"not finished after {budget_s} s (a hang)",
                        pytrace=False)
    if errs:
        raise errs[0]
    return out

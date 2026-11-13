"""The evidence store (results/confirm/evidence.jsonl, append only).

An entry is keyed by (collector, program hash, toolchain, arch, mode, opt,
offload, variant); a collector that finds its key reuses the stored
evidence instead of running again. Entries are never rewritten; a later
entry with the same key wins (a rerun)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from offload.engine.confirm.model import Evidence

from offload.engine.root import ROOT  # noqa: E402
DEFAULT = ROOT / "results" / "confirm" / "evidence.jsonl"


def _failed(e: Evidence) -> bool:
    return any(r.outcome == "harness_error" for r in e.runs)


class Store:
    def __init__(self, path: Path | None = DEFAULT, also_read=()):
        """`also_read`: stores read before `path` and never written (Task
        28: a batch shard reads the main store and appends to its own
        file, merged into the main store afterwards)."""
        self.path = Path(path) if path else None
        self._by: dict[tuple, Evidence] = {}
        self._lock = threading.Lock()
        for p in [Path(x) for x in also_read] + (
                [self.path] if self.path else []):
            if not p.is_file():
                continue
            for ln in p.read_text().splitlines():
                if ln.strip():
                    e = Evidence.from_dict(json.loads(ln))
                    if _failed(e):
                        continue   # a failed run is never read back
                    self._by[e.key] = e

    def get(self, key: tuple) -> Evidence | None:
        return self._by.get(key)

    def put(self, e: Evidence) -> Evidence:
        if _failed(e):
            return e          # runner failures are not cached
        with self._lock:
            old = self._by.get(e.key)
            if old is not None and old.to_dict() == e.to_dict():
                return e      # the same entry again (another process)
            self._by[e.key] = e
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(e.to_dict()) + "\n")
        return e

    def __len__(self) -> int:
        return len(self._by)

    def __bool__(self) -> bool:   # an empty store is still a store
        return True

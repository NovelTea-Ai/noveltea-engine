"""Shared "agents on screen" runner for the Pipeline's LLM jobs.

Same method as the Chapter Mechanics job: every worker thread is an agent (on Nvidia pinned to its own pooled key), items
are dealt round-robin across NOVELS so the agents sit on different novels, and each in-flight item is one row in the job's
live status (novel, chapter/unit, step, preview, agent #, key #) - which is what the Pipeline card draws.

    pool = AgentPool("thread_typing", model=label, want=4, exclusive_novel=True)
    pool.run(items, work)          # items: dicts with at least "novel"; optional "chapter", "unit", "preview"
    def work(item): ...; pool.step("calling the model", "preview text")   # inside a worker

exclusive_novel=True keeps at most one in-flight item per novel (jobs that rewrite one file per novel).
On any engine other than Nvidia there is one agent, so behaviour there is unchanged.
"""
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import llm_client as L

_TL = threading.local()


class AgentPool:
    def __init__(self, job: str, model: str = "", want: int = 4, exclusive_novel: bool = False):
        self.job = job
        self.model = model
        self.workers = L.nemotron_parallel_slots(max(1, want))
        self.exclusive = exclusive_novel
        self._lock = threading.Lock()
        self._rows: dict = {}
        self._queues: dict = {}      # novel -> deque of items
        self._order: deque = deque()  # novels in round-robin order
        self._busy: set = set()
        self.results: list = []

    # ── publishing ──
    def _publish(self):
        active = sorted(self._rows.values(), key=lambda r: (r.get("agent") or 99, r["started"]))
        last = active[-1] if active else {"novel": "", "step": "idle", "preview": ""}
        L.write_live_status(self.job, novel=last["novel"], kind=last["step"], batch_size=len(active),
                            preview=last["preview"], model=self.model, active=active)

    def _row(self, item: dict) -> dict:
        slot = getattr(L._NEM_SLOT, "slot", None)
        row = {"novel": item["novel"], "chapter": item.get("chapter"), "unit": item.get("unit", ""),
               "step": item.get("step", "working"), "preview": str(item.get("preview", ""))[:160],
               "started": time.strftime("%H:%M:%S"), "agent": (slot + 1) if slot is not None else None}
        if slot is not None and L._agent_engine() == "nemotron" and L.nemotron_pool_size():
            row["key"] = slot % L.nemotron_pool_size() + 1
        return row

    def step(self, step: str, preview: str = ""):
        """Called inside a worker: update the calling agent's row."""
        iid = getattr(_TL, "iid", None)
        with self._lock:
            row = self._rows.get(iid)
            if row:
                row.update(step=step, preview=str(preview)[:160])
            try:
                self._publish()
            except Exception:
                pass

    # ── scheduling: round-robin across novels ──
    def _take(self):
        with self._lock:
            for _ in range(len(self._order)):
                nv = self._order[0]
                self._order.rotate(-1)
                q = self._queues.get(nv)
                if not q or (self.exclusive and nv in self._busy):
                    continue
                item = q.popleft()
                if not q:
                    self._queues.pop(nv, None)
                    try:
                        self._order.remove(nv)
                    except ValueError:
                        pass
                self._busy.add(nv)
                return item
            return None

    def _remaining(self) -> bool:
        with self._lock:
            return any(self._queues.values())

    def _loop(self, fn):
        L.ensure_nemotron_slot()
        while True:
            item = self._take()
            if item is None:
                if not self._remaining():
                    return
                time.sleep(0.3)       # items left but their novels are busy: wait for a free one
                continue
            iid = id(item)
            _TL.iid = iid
            with self._lock:
                self._rows[iid] = self._row(item)
                try:
                    self._publish()
                except Exception:
                    pass
            try:
                res = fn(item)
                with self._lock:
                    self.results.append((item, res))
            except Exception as e:
                print(f"  agent: {item.get('novel')} {item.get('unit') or item.get('chapter')} failed ({e})")
                with self._lock:
                    self.results.append((item, e))
            finally:
                with self._lock:
                    self._rows.pop(iid, None)
                    self._busy.discard(item["novel"])
                    try:
                        self._publish()
                    except Exception:
                        pass

    def run(self, items: list, fn) -> list:
        """Run fn(item) for every item. Returns [(item, result-or-exception)] in completion order."""
        for it in items:
            self._queues.setdefault(it["novel"], deque()).append(it)
        self._order = deque(self._queues.keys())
        n = max(1, min(self.workers, len(items) or 1))
        with ThreadPoolExecutor(max_workers=n) as ex:
            for f in [ex.submit(self._loop, fn) for _ in range(n)]:
                f.result()
        return self.results

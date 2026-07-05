"""
ShootRunner - Job-queue executor for collection-level analysis.

The existing pipeline Runner processes one file; ShootRunner fans a
phase out across every asset in a shoot that still needs it, with
job-table bookkeeping so interrupted runs resume cleanly.

Two execution lanes:
- workers > 1: ThreadPoolExecutor for I/O-bound phases (ffprobe,
  ffmpeg extraction). Each worker opens its own DB connection.
- workers = 1: serial lane for model inference (Whisper, CLIP) where
  the model loads once and the GPU is the bottleneck anyway.

Worker functions receive (db, asset_row_dict, context) and may raise;
failures are recorded per-asset and never abort the batch.
"""
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from .db import ShootDB
from ..utils.progress import ProgressTracker

WorkerFn = Callable[[ShootDB, Dict[str, Any], Dict[str, Any]], None]


class ShootRunner:
    """Runs analysis phases over all assets in a shoot."""

    def __init__(self, db: ShootDB, shoot_id: int,
                 progress: Optional[ProgressTracker] = None):
        self.db = db
        self.shoot_id = shoot_id
        self.progress = progress or ProgressTracker()

    def run_phase(self, phase: str, fn: WorkerFn,
                  media_type: Optional[str] = None,
                  workers: int = 1,
                  context: Optional[Dict[str, Any]] = None,
                  tool_version: str = "") -> Dict[str, int]:
        """
        Run `fn` for every asset that hasn't completed `phase`.

        Returns counts: {ran, done, failed, skipped_total}.
        """
        context = context or {}
        assets = [dict(a) for a in
                  self.db.assets_needing(self.shoot_id, phase, media_type)]
        step = self.progress.start_step(phase, f"{len(assets)} assets")

        done = failed = 0
        if workers <= 1:
            for i, asset in enumerate(assets, 1):
                ok = self._run_one(self.db, phase, fn, asset, context, tool_version)
                done, failed = (done + 1, failed) if ok else (done, failed + 1)
                step.update(1, total=len(assets))
        else:
            def worker(asset):
                # sqlite3 connections are thread-local; open per task
                db = ShootDB(self.db.db_path)
                try:
                    return self._run_one(db, phase, fn, asset, context, tool_version)
                finally:
                    db.close()

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(worker, a) for a in assets]
                for future in as_completed(futures):
                    ok = future.result()
                    done, failed = (done + 1, failed) if ok else (done, failed + 1)
                    step.update(1, total=len(assets))

        if failed:
            step.error(f"{done} done, {failed} failed")
        else:
            step.complete(f"{done} done")
        return {"ran": len(assets), "done": done, "failed": failed}

    def _run_one(self, db: ShootDB, phase: str, fn: WorkerFn,
                 asset: Dict[str, Any], context: Dict[str, Any],
                 tool_version: str) -> bool:
        db.start_job(self.shoot_id, asset["id"], phase, tool_version)
        try:
            fn(db, asset, context)
            db.finish_job(asset["id"], phase, "done")
            return True
        except SkipAsset as e:
            db.finish_job(asset["id"], phase, "skipped", str(e))
            return True
        except Exception as e:
            db.finish_job(asset["id"], phase, "failed",
                          f"{e}\n{traceback.format_exc(limit=3)}"[:1000])
            return False


class SkipAsset(Exception):
    """Raise from a worker to mark an asset skipped (not failed) for a phase.

    Example: transcription skips assets whose VAD speech ratio is below
    threshold — that's a funnel decision, not an error.
    """

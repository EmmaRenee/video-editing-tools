"""
ShootDB - SQLite data layer for shoot-level processing.

One database per shoot, stored in the shoot workspace
(<shoot-root>/.videoedit/shoot.db by default). The database is the
contract between phases: ingest writes assets, analysis writes
scores/transcripts/scenes, review writes Claude's verdicts, and
timeline composition reads it all back.

Uses stdlib sqlite3 with WAL mode so interrupted runs (common on
NAS-scale shoots) never corrupt state. Every analysis phase records
a row in `jobs`; resume = re-run anything not marked 'done'.
"""
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

WORKSPACE_DIRNAME = ".videoedit"
DB_FILENAME = "shoot.db"

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS shoots (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    fps_default REAL DEFAULT 30.0,
    config_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    shoot_id INTEGER NOT NULL REFERENCES shoots(id),
    rel_path TEXT NOT NULL,
    abs_path TEXT NOT NULL,
    media_type TEXT NOT NULL,             -- video | audio | photo
    size_bytes INTEGER,
    quick_hash TEXT,                      -- blake2b of size + first/last 1MB
    mtime REAL,
    capture_ts TEXT,                      -- ISO timestamp from EXIF/QuickTime
    camera TEXT,
    lens TEXT,
    duration_s REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    vcodec TEXT,
    acodec TEXT,
    audio_channels INTEGER,
    status TEXT DEFAULT 'found',          -- found | probed | error
    error TEXT,
    UNIQUE(shoot_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(shoot_id, media_type);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    shoot_id INTEGER NOT NULL,
    asset_id INTEGER REFERENCES assets(id),
    phase TEXT NOT NULL,                  -- probe|scenes|vad|transcribe|embed|quality|events|photos|candidates|contact
    state TEXT DEFAULT 'pending',         -- pending | running | done | failed | skipped
    tool_version TEXT,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    UNIQUE(asset_id, phase)
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(shoot_id, phase, state);

CREATE TABLE IF NOT EXISTS transcripts (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(id),
    language TEXT,
    model TEXT,
    full_text TEXT,
    segments_json TEXT                    -- [{start,end,text,words:[...]}]
);

CREATE TABLE IF NOT EXISTS scenes (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    start_s REAL NOT NULL,
    end_s REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_asset ON scenes(asset_id);

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    ts_s REAL NOT NULL,
    thumb_path TEXT,
    sharpness REAL,
    exposure_low_pct REAL,
    exposure_high_pct REAL,
    embedding BLOB                        -- float16-packed vector
);
CREATE INDEX IF NOT EXISTS idx_frames_asset ON frames(asset_id);

CREATE TABLE IF NOT EXISTS frame_tags (
    frame_id INTEGER NOT NULL REFERENCES frames(id),
    label TEXT NOT NULL,
    score REAL,
    source TEXT DEFAULT 'clip_zeroshot'   -- clip_zeroshot | claude
);
CREATE INDEX IF NOT EXISTS idx_frame_tags ON frame_tags(frame_id);

CREATE TABLE IF NOT EXISTS audio_features (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    start_s REAL,
    end_s REAL,
    kind TEXT NOT NULL,                   -- rms_peak | speech | event
    label TEXT,
    score REAL
);
CREATE INDEX IF NOT EXISTS idx_audio_asset ON audio_features(asset_id, kind);

CREATE TABLE IF NOT EXISTS photo_groups (
    id INTEGER PRIMARY KEY,
    shoot_id INTEGER NOT NULL,
    method TEXT DEFAULT 'time_camera',
    label TEXT,
    start_ts TEXT,
    end_ts TEXT
);

CREATE TABLE IF NOT EXISTS photo_group_members (
    group_id INTEGER NOT NULL REFERENCES photo_groups(id),
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    dedupe_cluster INTEGER,
    local_rank INTEGER,
    is_keeper_suggested INTEGER DEFAULT 0,   -- local (mechanical) suggestion
    claude_keep INTEGER,                     -- Claude verdict: 1 keep, 0 reject
    claude_hero INTEGER DEFAULT 0,           -- Claude verdict: group hero shot
    UNIQUE(group_id, asset_id)
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    kind_guess TEXT,                      -- aroll | broll | mixed
    local_score REAL,
    signals_json TEXT,                    -- {speech_ratio, motion, rms_peak_db, top_tags, ...}
    contact_sheet_path TEXT,
    transcript_excerpt TEXT,
    status TEXT DEFAULT 'unreviewed',     -- unreviewed | shortlisted | claude_reviewed | rejected
    claude_rank INTEGER,
    claude_kind TEXT,
    claude_in_s REAL,
    claude_out_s REAL,
    claude_story_beat TEXT,
    claude_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_asset ON candidates(asset_id);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);

CREATE TABLE IF NOT EXISTS claude_reviews (
    id INTEGER PRIMARY KEY,
    target_kind TEXT NOT NULL,            -- candidate | photo_group
    target_id INTEGER,
    verdict_json TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timelines (
    id INTEGER PRIMARY KEY,
    shoot_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    otio_path TEXT,
    edl_path TEXT,
    resolve_project TEXT,
    resolve_timeline TEXT,
    created_at TEXT NOT NULL
);
"""


def quick_hash(path: Path, size: Optional[int] = None) -> str:
    """
    Cheap content fingerprint: blake2b over file size + first/last 1MB.

    Full-file hashing 100s of GB over NAS takes hours; this reads at
    most 2MB per file and still catches truncation, re-exports, and
    swapped files.
    """
    path = Path(path)
    if size is None:
        size = path.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    chunk = 1024 * 1024
    with open(path, "rb") as f:
        h.update(f.read(chunk))
        if size > 2 * chunk:
            f.seek(-chunk, 2)
            h.update(f.read(chunk))
    return h.hexdigest()


class ShootDB:
    """SQLite wrapper for a single shoot's state."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ------------------------------------------------------------------
    # Setup / discovery

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()

    @classmethod
    def open_workspace(cls, shoot_root: Path, workspace: Optional[Path] = None) -> "ShootDB":
        """Open (creating if needed) the DB for a shoot root directory."""
        workspace = Path(workspace) if workspace else Path(shoot_root) / WORKSPACE_DIRNAME
        return cls(workspace / DB_FILENAME)

    @classmethod
    def find(cls, start: Path) -> Optional["ShootDB"]:
        """Walk up from `start` looking for an existing shoot workspace."""
        current = Path(start).resolve()
        for candidate in [current, *current.parents]:
            db_path = candidate / WORKSPACE_DIRNAME / DB_FILENAME
            if db_path.exists():
                return cls(db_path)
        return None

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------
    # Shoots

    def init_shoot(self, name: str, root_path: Path, workspace_path: Path,
                   fps_default: float = 30.0, config: Optional[Dict] = None) -> int:
        row = self.conn.execute("SELECT id FROM shoots WHERE root_path = ?",
                                (str(root_path),)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO shoots (name, root_path, workspace_path, fps_default, config_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, str(root_path), str(workspace_path), fps_default,
             json.dumps(config or {}), datetime.now().isoformat()))
        self.conn.commit()
        return cur.lastrowid

    def get_shoot(self, shoot_id: Optional[int] = None) -> Optional[sqlite3.Row]:
        if shoot_id is None:
            return self.conn.execute("SELECT * FROM shoots ORDER BY id LIMIT 1").fetchone()
        return self.conn.execute("SELECT * FROM shoots WHERE id = ?", (shoot_id,)).fetchone()

    def get_config(self, shoot_id: int) -> Dict[str, Any]:
        row = self.get_shoot(shoot_id)
        return json.loads(row["config_json"]) if row else {}

    def update_config(self, shoot_id: int, updates: Dict[str, Any]):
        config = self.get_config(shoot_id)
        config.update(updates)
        self.conn.execute("UPDATE shoots SET config_json = ? WHERE id = ?",
                          (json.dumps(config), shoot_id))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Assets

    def upsert_asset(self, shoot_id: int, rel_path: str, abs_path: str,
                     media_type: str, size_bytes: int, mtime: float) -> tuple[int, bool]:
        """
        Insert or refresh an asset row.

        Returns (asset_id, changed). `changed` is True when the asset is
        new or its size/mtime differ from the stored row — the signal
        that downstream analysis must re-run.
        """
        row = self.conn.execute(
            "SELECT id, size_bytes, mtime FROM assets WHERE shoot_id = ? AND rel_path = ?",
            (shoot_id, rel_path)).fetchone()
        if row:
            if row["size_bytes"] == size_bytes and row["mtime"] == mtime:
                return row["id"], False
            self.conn.execute(
                "UPDATE assets SET size_bytes = ?, mtime = ?, status = 'found', "
                "quick_hash = NULL, error = NULL WHERE id = ?",
                (size_bytes, mtime, row["id"]))
            self.reset_jobs(row["id"])
            self.conn.commit()
            return row["id"], True
        cur = self.conn.execute(
            "INSERT INTO assets (shoot_id, rel_path, abs_path, media_type, size_bytes, mtime) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (shoot_id, rel_path, abs_path, media_type, size_bytes, mtime))
        self.conn.commit()
        return cur.lastrowid, True

    def update_asset(self, asset_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE assets SET {cols} WHERE id = ?",
                          (*fields.values(), asset_id))
        self.conn.commit()

    def get_asset(self, asset_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()

    def list_assets(self, shoot_id: int, media_type: Optional[str] = None,
                    status: Optional[str] = None) -> List[sqlite3.Row]:
        query = "SELECT * FROM assets WHERE shoot_id = ?"
        params: List[Any] = [shoot_id]
        if media_type:
            query += " AND media_type = ?"
            params.append(media_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY rel_path"
        return self.conn.execute(query, params).fetchall()

    # ------------------------------------------------------------------
    # Jobs (resume/idempotency backbone)

    def job_state(self, asset_id: int, phase: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT state FROM jobs WHERE asset_id = ? AND phase = ?",
            (asset_id, phase)).fetchone()
        return row["state"] if row else None

    def assets_needing(self, shoot_id: int, phase: str,
                       media_type: Optional[str] = None) -> List[sqlite3.Row]:
        """Assets with no 'done' or 'skipped' job for this phase."""
        query = """
            SELECT a.* FROM assets a
            LEFT JOIN jobs j ON j.asset_id = a.id AND j.phase = ?
            WHERE a.shoot_id = ? AND a.status != 'error'
              AND (j.state IS NULL OR j.state NOT IN ('done', 'skipped'))
        """
        params: List[Any] = [phase, shoot_id]
        if media_type:
            query += " AND a.media_type = ?"
            params.append(media_type)
        return self.conn.execute(query + " ORDER BY a.rel_path", params).fetchall()

    def start_job(self, shoot_id: int, asset_id: int, phase: str,
                  tool_version: str = ""):
        self.conn.execute(
            "INSERT INTO jobs (shoot_id, asset_id, phase, state, tool_version, started_at) "
            "VALUES (?, ?, ?, 'running', ?, ?) "
            "ON CONFLICT(asset_id, phase) DO UPDATE SET "
            "state = 'running', tool_version = excluded.tool_version, "
            "started_at = excluded.started_at, finished_at = NULL, error = NULL",
            (shoot_id, asset_id, phase, tool_version, datetime.now().isoformat()))
        self.conn.commit()

    def finish_job(self, asset_id: int, phase: str, state: str = "done",
                   error: Optional[str] = None):
        self.conn.execute(
            "UPDATE jobs SET state = ?, finished_at = ?, error = ? "
            "WHERE asset_id = ? AND phase = ?",
            (state, datetime.now().isoformat(), error, asset_id, phase))
        self.conn.commit()

    def reset_jobs(self, asset_id: int, phases: Optional[Iterable[str]] = None):
        """Invalidate analysis for a changed asset (all phases by default)."""
        if phases:
            marks = ",".join("?" for _ in phases)
            self.conn.execute(
                f"DELETE FROM jobs WHERE asset_id = ? AND phase IN ({marks})",
                (asset_id, *phases))
        else:
            self.conn.execute("DELETE FROM jobs WHERE asset_id = ?", (asset_id,))
        self.conn.commit()

    def phase_counts(self, shoot_id: int) -> Dict[str, Dict[str, int]]:
        """Per-phase job-state counts for `shoot status`."""
        rows = self.conn.execute(
            "SELECT phase, state, COUNT(*) AS n FROM jobs WHERE shoot_id = ? "
            "GROUP BY phase, state", (shoot_id,)).fetchall()
        counts: Dict[str, Dict[str, int]] = {}
        for row in rows:
            counts.setdefault(row["phase"], {})[row["state"]] = row["n"]
        return counts

    # ------------------------------------------------------------------
    # Analysis writes (used by Phase 2+; defined here so the schema and
    # its access patterns live together)

    def save_transcript(self, asset_id: int, language: str, model: str,
                        full_text: str, segments: List[Dict]):
        self.conn.execute(
            "INSERT OR REPLACE INTO transcripts (asset_id, language, model, full_text, segments_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (asset_id, language, model, full_text, json.dumps(segments)))
        self.conn.commit()

    def save_scenes(self, asset_id: int, scenes: List[tuple[float, float]]):
        self.conn.execute("DELETE FROM scenes WHERE asset_id = ?", (asset_id,))
        self.conn.executemany(
            "INSERT INTO scenes (asset_id, start_s, end_s) VALUES (?, ?, ?)",
            [(asset_id, s, e) for s, e in scenes])
        self.conn.commit()

    def save_frame(self, asset_id: int, ts_s: float, thumb_path: Optional[str] = None,
                   sharpness: Optional[float] = None,
                   exposure_low_pct: Optional[float] = None,
                   exposure_high_pct: Optional[float] = None,
                   embedding: Optional[bytes] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO frames (asset_id, ts_s, thumb_path, sharpness, "
            "exposure_low_pct, exposure_high_pct, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_id, ts_s, thumb_path, sharpness, exposure_low_pct,
             exposure_high_pct, embedding))
        self.conn.commit()
        return cur.lastrowid

    def save_audio_features(self, asset_id: int, kind: str,
                            features: List[Dict[str, Any]]):
        """features: [{start_s, end_s, label, score}]"""
        self.conn.execute(
            "DELETE FROM audio_features WHERE asset_id = ? AND kind = ?",
            (asset_id, kind))
        self.conn.executemany(
            "INSERT INTO audio_features (asset_id, start_s, end_s, kind, label, score) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(asset_id, f.get("start_s"), f.get("end_s"), kind,
              f.get("label"), f.get("score")) for f in features])
        self.conn.commit()

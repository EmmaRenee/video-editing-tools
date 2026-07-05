#!/bin/bash
# End-to-end funnel verification on synthetic fixtures.
# Requires the [analyze] extra installed. Run from the repo root:
#   bash tests/e2e_fixture_shoot.sh
set -euo pipefail

cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"
VE="$VENV/bin/videoedit"
PY="$VENV/bin/python"
SHOOT=/tmp/e2e_shoot

rm -rf "$SHOOT"
bash tests/fixtures/make_fixtures.sh "$SHOOT" >/dev/null

$VE shoot init "$SHOOT" --name "E2E" >/dev/null
$VE shoot scan --root "$SHOOT"
$VE shoot analyze --root "$SHOOT" --whisper-model tiny --only scenes,vad,transcribe,embed,quality,photos
$VE shoot candidates --root "$SHOOT"
$VE shoot contact-sheets --root "$SHOOT" --top 20
$VE shoot review-export --root "$SHOOT"
$VE shoot review-export --root "$SHOOT" --photos
$VE shoot status --root "$SHOOT"

# assertions
$PY - "$SHOOT" << 'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, "src/python")
from videoedit.shoot.db import ShootDB

shoot_root = Path(sys.argv[1])
db = ShootDB.open_workspace(shoot_root)
shoot_id = db.get_shoot()["id"]

def one(sql, *args):
    return db.conn.execute(sql, args).fetchone()

# 1. speech gate: 'interview' (tone bursts) should out-speech silent b-roll
def ratio(name):
    row = one("""SELECT f.score FROM audio_features f JOIN assets a ON a.id=f.asset_id
                 WHERE a.rel_path LIKE ? AND f.kind='speech_ratio'""", f"%{name}%")
    return row["score"] if row else None

r_int, r_silent = ratio("interview"), ratio("broll_silent")
assert r_silent is not None and r_silent < 0.1, f"silent b-roll ratio {r_silent}"
print(f"speech_ratio interview={r_int} silent_broll={r_silent}")

# 2. scenes + frames + embeddings exist for videos
n_scenes = one("SELECT COUNT(*) c FROM scenes")["c"]
n_frames = one("SELECT COUNT(*) c FROM frames WHERE embedding IS NOT NULL")["c"]
assert n_scenes >= 3 and n_frames >= 3, (n_scenes, n_frames)
print(f"scenes={n_scenes} embedded_frames={n_frames}")

# 3. photo cull: blurred IMG_0002 ranked below sharp shots in its group
rows = db.conn.execute("""SELECT a.rel_path, m.local_rank FROM photo_group_members m
                          JOIN assets a ON a.id=m.asset_id""").fetchall()
ranks = {Path(r["rel_path"]).name: r["local_rank"] for r in rows}
assert ranks, "no photo group members"
sharp_ranks = [v for k, v in ranks.items() if k != "IMG_0002.jpg"]
assert all(ranks["IMG_0002.jpg"] > r for r in sharp_ranks if r), ranks
print(f"photo ranks={ranks}")

# 4. candidates generated with kinds
cands = db.conn.execute("SELECT kind_guess, COUNT(*) c FROM candidates GROUP BY kind_guess").fetchall()
assert cands, "no candidates"
print("candidates:", {r["kind_guess"]: r["c"] for r in cands})

# 5. review export excludes nothing yet, sheets referenced
batch = json.loads((Path(db.get_shoot()["workspace_path"]) / "reviews" / "review_batch.json").read_text())
assert batch["candidates"], "empty review batch"
assert batch["sheet_paths"], "no sheets referenced"
for sheet in batch["sheet_paths"]:
    assert Path(sheet).exists(), sheet
print(f"review batch: {len(batch['candidates'])} candidates, {len(batch['sheet_paths'])} sheets")
print("E2E OK")
EOF

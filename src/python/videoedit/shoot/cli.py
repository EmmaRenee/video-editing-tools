"""
Shoot CLI - `videoedit shoot ...` command group.

Collection-level commands operating on a whole shoot directory,
backed by the shoot database. Run from anywhere inside a shoot
(commands walk up to find the workspace) or pass --root.
"""
import sys
from pathlib import Path

import click

from .db import ShootDB, WORKSPACE_DIRNAME


def _open(root: str = None) -> tuple:
    """Locate the shoot DB from --root or the cwd. Exits with help if absent."""
    if root:
        db = ShootDB.open_workspace(Path(root))
    else:
        db = ShootDB.find(Path.cwd())
    if db is None:
        click.echo("No shoot workspace found. Run `videoedit shoot init <dir>` first.",
                   err=True)
        sys.exit(1)
    shoot = db.get_shoot()
    if shoot is None:
        click.echo("Workspace exists but no shoot registered. "
                   "Run `videoedit shoot init <dir>`.", err=True)
        sys.exit(1)
    return db, shoot


@click.group()
def shoot():
    """Process a whole shoot: ingest, analyze, review, rough cut."""


@shoot.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--name", help="Shoot name (default: directory name)")
@click.option("--workspace", type=click.Path(),
              help=f"Workspace location (default: <dir>/{WORKSPACE_DIRNAME}). "
                   "Point at local scratch when the shoot lives on a NAS.")
@click.option("--fps", type=float, default=30.0, show_default=True,
              help="Default timeline frame rate")
def init(directory, name, workspace, fps):
    """Initialize a shoot workspace for DIRECTORY."""
    root = Path(directory).resolve()
    workspace_path = Path(workspace).resolve() if workspace else root / WORKSPACE_DIRNAME
    db = ShootDB.open_workspace(root, workspace_path)
    shoot_id = db.init_shoot(name or root.name, root, workspace_path, fps_default=fps)
    click.echo(f"Shoot #{shoot_id} '{name or root.name}' initialized")
    click.echo(f"  Root:      {root}")
    click.echo(f"  Workspace: {workspace_path}")
    click.echo("\nNext: videoedit shoot scan")


@shoot.command()
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--workers", type=int, default=4, show_default=True,
              help="Parallel probe workers (keep low on NAS)")
def scan(root, workers):
    """Scan for media files and probe metadata (idempotent)."""
    from . import scanner

    db, shoot_row = _open(root)
    click.echo(f"Scanning: {shoot_row['root_path']}")

    def on_progress(done, total):
        if done % 25 == 0 or done == total:
            click.echo(f"  probed {done}/{total}")

    summary = scanner.scan(db, shoot_row["id"], workers=workers,
                           on_progress=on_progress)
    click.echo(f"\nFound {summary['found']} media files "
               f"({summary['new_or_changed']} new/changed)")
    if summary["probed"] or summary["failed"]:
        click.echo(f"Probed {summary['probed']}, failed {summary['failed']}")
    if summary["failed"]:
        click.echo("Failed files are marked in the DB; see `videoedit shoot report`.")


@shoot.command()
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
def status(root):
    """Show asset counts and per-phase job progress."""
    db, shoot_row = _open(root)
    shoot_id = shoot_row["id"]

    assets = db.list_assets(shoot_id)
    by_type = {}
    for a in assets:
        by_type[a["media_type"]] = by_type.get(a["media_type"], 0) + 1

    click.echo(f"Shoot: {shoot_row['name']} ({shoot_row['root_path']})")
    click.echo(f"Assets: {len(assets)} "
               f"({', '.join(f'{v} {k}' for k, v in sorted(by_type.items()))})")

    total_gb = sum(a["size_bytes"] or 0 for a in assets) / 1024**3
    total_dur = sum(a["duration_s"] or 0 for a in assets)
    click.echo(f"Size: {total_gb:.1f} GB | AV duration: "
               f"{int(total_dur // 3600)}h{int(total_dur % 3600 // 60):02d}m")

    counts = db.phase_counts(shoot_id)
    if counts:
        click.echo("\nPhases:")
        for phase, states in counts.items():
            parts = ", ".join(f"{n} {state}" for state, n in sorted(states.items()))
            click.echo(f"  {phase:12} {parts}")

    unreviewed = db.conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE status = 'unreviewed'").fetchone()[0]
    reviewed = db.conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE status = 'claude_reviewed'").fetchone()[0]
    if unreviewed or reviewed:
        click.echo(f"\nCandidates: {reviewed} reviewed, {unreviewed} awaiting review")


@shoot.command()
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--only", help="Comma-separated phases to run "
                             "(scenes,vad,transcribe,embed,quality,events,photos)")
@click.option("--workers", type=int, default=2, show_default=True,
              help="Parallel workers for I/O-bound phases")
@click.option("--whisper-model", default="small", show_default=True,
              help="Whisper model size for transcription")
def analyze(root, only, workers, whisper_model):
    """Run local analysis: scenes, speech, transcripts, embeddings, photos."""
    from . import analyze as analyze_mod

    db, shoot_row = _open(root)
    phases = [p.strip() for p in only.split(",")] if only else None
    if phases:
        bad = set(phases) - set(analyze_mod.PHASES)
        if bad:
            click.echo(f"Unknown phases: {', '.join(bad)}. "
                       f"Valid: {', '.join(analyze_mod.PHASES)}", err=True)
            sys.exit(1)

    summary = analyze_mod.analyze_shoot(
        db, shoot_row["id"], only=phases, workers=workers,
        whisper_model=whisper_model)

    click.echo("\nAnalysis summary:")
    for phase, counts in summary.items():
        parts = ", ".join(f"{v} {k}" for k, v in counts.items())
        click.echo(f"  {phase:12} {parts}")
    click.echo("\nNext: videoedit shoot candidates")


@shoot.command()
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
def candidates(root):
    """Fuse analysis signals into ranked A/B-roll clip candidates."""
    from . import candidates as candidates_mod

    db, shoot_row = _open(root)
    summary = candidates_mod.generate_candidates(db, shoot_row["id"])
    click.echo(f"Scored {summary['scenes_scored']} scenes → "
               f"{summary['candidates']} candidates")
    click.echo("\nNext: videoedit shoot contact-sheets")


@shoot.command("contact-sheets")
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--top", type=int, default=60, show_default=True,
              help="How many top candidates to sheet")
@click.option("--candidate", type=int,
              help="Build a dense in/out refinement strip for one candidate id")
def contact_sheets(root, top, candidate):
    """Build contact-sheet grids for Claude to review visually."""
    from . import review as review_mod

    db, shoot_row = _open(root)
    sheets = review_mod.build_contact_sheets(db, shoot_row["id"], top_n=top,
                                             candidate_id=candidate)
    if not sheets:
        click.echo("No candidates with thumbnails to sheet — "
                   "run `shoot analyze` and `shoot candidates` first.")
        return
    for sheet in sheets:
        click.echo(f"Sheet: {sheet}")


@shoot.command("review-export")
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--top", type=int, default=60, show_default=True)
@click.option("--photos", "photos_flag", is_flag=True,
              help="Export photo groups instead of clip candidates")
@click.option("--output", "-o", type=click.Path(), help="Output JSON path")
def review_export(root, top, photos_flag, output):
    """Export a review batch JSON (+ sheets) for Claude."""
    from . import review as review_mod

    db, shoot_row = _open(root)
    out_path = Path(output) if output else None
    if photos_flag:
        path = review_mod.export_photo_batch(db, shoot_row["id"], output=out_path)
    else:
        path = review_mod.export_review_batch(db, shoot_row["id"], top_n=top,
                                              output=out_path)
    click.echo(f"Review batch: {path}")


@shoot.command("review-import")
@click.argument("verdict_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--model", default="", help="Model name for the audit trail")
def review_import(verdict_file, root, model):
    """Import Claude's verdict JSON (clip reviews or photo culls)."""
    from . import review as review_mod

    db, shoot_row = _open(root)
    try:
        summary = review_mod.import_verdicts(db, shoot_row["id"],
                                             Path(verdict_file), model=model)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    click.echo(f"Applied {summary['applied']} verdicts"
               + (f" ({summary['missing']} referenced unknown ids)"
                  if summary["missing"] else ""))


@shoot.command()
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
def timeline(spec_file, root):
    """Register a rough-cut spec JSON and write its .otio file."""
    from . import review as review_mod

    db, shoot_row = _open(root)
    try:
        timeline_id = review_mod.save_timeline_spec(db, shoot_row["id"],
                                                    Path(spec_file))
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)

    row = db.conn.execute("SELECT * FROM timelines WHERE id = ?",
                          (timeline_id,)).fetchone()
    otio_path = None
    try:
        import json as json_mod
        from ..resolve.otio_export import export_otio
        spec = json_mod.loads(row["spec_json"])
        otio_path = export_otio(
            db, spec,
            Path(shoot_row["workspace_path"]) / "timelines"
            / f"{spec['timeline_name']}.otio")
        db.conn.execute("UPDATE timelines SET otio_path = ? WHERE id = ?",
                        (str(otio_path), timeline_id))
        db.conn.commit()
    except ImportError:
        click.echo("(opentimelineio not installed — skipping .otio export; "
                   "pip install 'videoedit[resolve]')")

    click.echo(f"Timeline #{timeline_id} registered: {row['name']}")
    if otio_path:
        click.echo(f"OTIO: {otio_path}")
        click.echo("Import manually in Resolve (File → Import → Timeline) or:")
    click.echo(f"  videoedit shoot resolve-push {timeline_id}")


@shoot.command("resolve-push")
@click.argument("timeline_id", type=int)
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--project", "project_name",
              help="Resolve project name (default: currently open project)")
@click.option("--include-rejected", is_flag=True,
              help="Also import rejected clips into a Rejected bin")
def resolve_push(timeline_id, root, project_name, include_rejected):
    """Build the rough cut inside a running DaVinci Resolve Studio."""
    import json as json_mod
    from ..resolve.api import get_resolve, get_project, ResolveConnectionError
    from ..resolve.project import import_shoot_media
    from ..resolve.timeline import build_timeline

    db, shoot_row = _open(root)
    row = db.conn.execute("SELECT * FROM timelines WHERE id = ?",
                          (timeline_id,)).fetchone()
    if row is None:
        click.echo(f"No timeline #{timeline_id} — run `shoot timeline` first.",
                   err=True)
        sys.exit(1)
    spec = json_mod.loads(row["spec_json"])

    try:
        resolve = get_resolve()
        project = get_project(resolve, project_name)
    except ResolveConnectionError as e:
        click.echo(f"Resolve connection failed: {e}", err=True)
        if row["otio_path"]:
            click.echo(f"\nFallback: import the OTIO manually:\n  {row['otio_path']}")
        sys.exit(1)

    click.echo(f"Connected to Resolve project: {project.GetName()}")
    click.echo("Importing media into bins...")
    path_to_item = import_shoot_media(project, db, shoot_row["id"],
                                      include_rejected=include_rejected)
    click.echo(f"  {len(path_to_item)} clips in media pool")

    click.echo(f"Building timeline '{spec['timeline_name']}'...")
    timeline_obj = build_timeline(project, db, spec, path_to_item)

    db.conn.execute(
        "UPDATE timelines SET resolve_project = ?, resolve_timeline = ? WHERE id = ?",
        (project.GetName(), timeline_obj.GetName(), timeline_id))
    db.conn.commit()
    click.echo(f"✓ Timeline '{timeline_obj.GetName()}' created in Resolve")


@shoot.command()
@click.option("--root", type=click.Path(exists=True), help="Shoot root directory")
@click.option("--output", "-o", default="inventory", help="Output filename base")
@click.option("--format", "-f", "formats", multiple=True,
              type=click.Choice(["csv", "md", "json"]), default=("csv", "md", "json"))
def report(root, output, formats):
    """Generate inventory reports (CSV/Markdown/JSON) from the shoot DB."""
    from . import reports

    db, shoot_row = _open(root)
    rows = reports.inventory_rows(db, shoot_row["id"])
    if not rows:
        click.echo("No assets in DB — run `videoedit shoot scan` first.")
        return

    base = Path(output)
    if "csv" in formats:
        reports.write_csv(rows, base.with_suffix(".csv"))
        click.echo(f"CSV: {base.with_suffix('.csv')}")
    if "md" in formats:
        reports.write_markdown(db, shoot_row["id"], rows, base.with_suffix(".md"))
        click.echo(f"Markdown: {base.with_suffix('.md')}")
    if "json" in formats:
        reports.write_json(db, shoot_row["id"], rows, base.with_suffix(".json"))
        click.echo(f"JSON: {base.with_suffix('.json')}")

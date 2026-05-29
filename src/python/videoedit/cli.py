"""Command line interface for videoedit."""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .config import AnalysisConfig
from .diagnostics import format_diagnostics, run_diagnostics
from .edl import export_selection_file
from .inventory import build_inventory, write_inventory_outputs
from .operations import default_registry, op_extract_segments
from .pipeline import load_pipeline, plan_pipeline, run_pipeline, validate_pipeline, write_preset
from .presets import PRESETS
from .rating import run_rating
from .review import assemble, create_approval_file, generate_review_assets


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="videoedit", description="Local-first video editing pipeline tools")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser("inventory", help="Scan footage and write inventory artifacts")
    inventory.add_argument("footage")
    inventory.add_argument("--output", "-o", required=True)
    inventory.set_defaults(func=cmd_inventory)

    rate = sub.add_parser("rate", help="Inventory, rate, and rank footage")
    add_rate_args(rate)
    rate.set_defaults(func=cmd_rate)

    export_edl = sub.add_parser("export-edl", help="Generate EDL/XML/M3U artifacts from selection JSON")
    export_edl.add_argument("selections", nargs="+")
    export_edl.add_argument("--output", "-o", required=True)
    export_edl.add_argument("--fps", type=float, default=30.0)
    export_edl.set_defaults(func=cmd_export_edl)

    extract_segments = sub.add_parser("extract-segments", help="Extract clips from selection JSON files")
    extract_segments.add_argument("selections", nargs="+")
    extract_segments.add_argument("--output", "-o", required=True)
    extract_segments.set_defaults(func=cmd_extract_segments)

    review_assets = sub.add_parser("review-assets", help="Generate thumbnails and an HTML contact sheet")
    review_assets.add_argument("ratings")
    review_assets.add_argument("--output", "-o", required=True)
    review_assets.add_argument("--max-items", type=int, default=100)
    review_assets.add_argument("--proxy", action="store_true", help="Also render low-resolution proxy clips")
    review_assets.add_argument("--thumb-width", type=int, default=360)
    review_assets.set_defaults(func=cmd_review_assets)

    approve = sub.add_parser("approve", help="Create approved.json from ratings candidates")
    approve.add_argument("ratings")
    approve.add_argument("--output", "-o", required=True)
    approve.add_argument("--actions", default="select,review", help="Comma-separated actions to approve")
    approve.add_argument("--min-score", type=int)
    approve.add_argument("--ids", help="Comma-separated clip IDs to approve explicitly")
    approve.add_argument("--decisions", help="Editable review_decisions.json from review-assets")
    approve.set_defaults(func=cmd_approve)

    init = sub.add_parser("init", help="Write a pipeline preset YAML")
    init.add_argument("preset", choices=sorted(PRESETS))
    init.add_argument("--output", "-o", required=True)
    init.set_defaults(func=cmd_init)

    validate = sub.add_parser("validate", help="Validate a pipeline YAML file")
    validate.add_argument("pipeline")
    validate.set_defaults(func=cmd_validate)

    run = sub.add_parser("run", help="Run a pipeline YAML file")
    run.add_argument("pipeline")
    run.add_argument("--input", "-i", required=True)
    run.add_argument("--output", "-o", required=True)
    run.add_argument("--dry-run", action="store_true", help="Validate and print the execution plan without running steps")
    run.set_defaults(func=cmd_run)

    plan = sub.add_parser("plan", help="Validate a pipeline and print its resolved execution plan")
    plan.add_argument("pipeline")
    plan.add_argument("--input", "-i", required=True)
    plan.add_argument("--output", "-o", required=True)
    plan.set_defaults(func=cmd_plan)

    operations = sub.add_parser("operations", help="List available operations")
    operations.set_defaults(func=cmd_operations)

    doctor = sub.add_parser("doctor", help="Check required and optional local dependencies")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")
    doctor.set_defaults(func=cmd_doctor)

    assemble_cmd = sub.add_parser("assemble", help="Assemble a rough cut from selection or approved JSON")
    assemble_cmd.add_argument("selection")
    assemble_cmd.add_argument("--output", "-o", required=True)
    assemble_cmd.set_defaults(func=cmd_assemble)

    return parser


def add_rate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("footage")
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--config")
    parser.add_argument("--transcript", choices=["off", "auto", "required"], default=None)
    parser.add_argument("--transcript-dir")
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--min-select-score", type=int)
    parser.add_argument("--min-review-score", type=int)
    parser.add_argument("--window-pre-roll", type=float)
    parser.add_argument("--window-post-roll", type=float)
    parser.add_argument("--scene-threshold", type=float)
    parser.add_argument("--silence-threshold", type=float)
    parser.add_argument("--no-cache", action="store_true")


def config_from_args(args: argparse.Namespace) -> AnalysisConfig:
    config = AnalysisConfig.from_file(args.config)
    if args.transcript is not None:
        config.transcript_mode = args.transcript
    if args.transcript_dir:
        config.transcript_dir = args.transcript_dir
    if args.max_candidates is not None:
        config.max_candidates = args.max_candidates
    if args.min_select_score is not None:
        config.min_select_score = args.min_select_score
    if args.min_review_score is not None:
        config.min_review_score = args.min_review_score
    if args.window_pre_roll is not None:
        config.window_pre_roll = args.window_pre_roll
    if args.window_post_roll is not None:
        config.window_post_roll = args.window_post_roll
    if args.scene_threshold is not None:
        config.scene_threshold = args.scene_threshold
    if args.silence_threshold is not None:
        config.silence_threshold_db = args.silence_threshold
    if args.no_cache:
        config.cache = False
    return config


def cmd_inventory(args: argparse.Namespace) -> int:
    items = build_inventory(args.footage)
    write_inventory_outputs(items, os.path.join(args.output, "inventory"))
    print(f"Inventory written to {args.output}")
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    report = run_rating(args.footage, args.output, config=config_from_args(args))
    print(json.dumps(report.summary, indent=2))
    return 0


def cmd_export_edl(args: argparse.Namespace) -> int:
    output = args.output
    written = []
    for value in args.selections:
        paths = _expand_paths(value)
        for path in paths:
            written.extend(export_selection_file(path, output, fps=args.fps))
    print(f"Wrote {len(written)} handoff files to {output}")
    return 0


def cmd_extract_segments(args: argparse.Namespace) -> int:
    written = []
    for value in args.selections:
        result = op_extract_segments({}, {"input": value, "output": args.output})
        written.extend(result["files"])
    print(json.dumps({"output": args.output, "files": written}, indent=2))
    return 0


def cmd_review_assets(args: argparse.Namespace) -> int:
    result = generate_review_assets(
        args.ratings,
        args.output,
        max_items=args.max_items,
        proxies=args.proxy,
        thumbnail_width=args.thumb_width,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    output = create_approval_file(
        args.ratings,
        args.output,
        actions=_split_csv(args.actions),
        min_score=args.min_score,
        ids=_split_csv(args.ids),
        decisions_json=args.decisions,
    )
    print(f"Approved selections written to {output}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    write_preset(args.preset, args.output)
    print(f"Wrote {args.preset} pipeline to {args.output}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    pipeline = load_pipeline(args.pipeline)
    validate_pipeline(pipeline)
    print(f"Pipeline OK: {pipeline.get('name', args.pipeline)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(json.dumps(plan_pipeline(args.pipeline, args.input, args.output), indent=2))
        return 0
    context = run_pipeline(args.pipeline, args.input, args.output)
    print(json.dumps({"manifest": context.get("manifest"), "results": context["results"]}, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    print(json.dumps(plan_pipeline(args.pipeline, args.input, args.output), indent=2))
    return 0


def cmd_operations(args: argparse.Namespace) -> int:
    for operation in default_registry().list():
        print(f"{operation.name:28} {operation.description}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_diagnostics()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_diagnostics(report))
    return 0 if report["status"] == "ok" else 1


def cmd_assemble(args: argparse.Namespace) -> int:
    output = assemble(args.selection, args.output)
    print(f"Rough cut written to {output}")
    return 0


def _expand_paths(value: str) -> list[str]:
    if any(char in value for char in "*?[]"):
        return sorted(glob.glob(value))
    path = os.fspath(value)
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.json")))
    return [path]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())

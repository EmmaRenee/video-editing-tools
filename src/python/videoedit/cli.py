"""Command line interface for videoedit."""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .calibration import evaluate_ratings, init_annotation_file, tune_scoring
from .captions import burn_captions, list_caption_styles
from .config import AnalysisConfig
from .content import generate_content_map, generate_quote_mining, list_series_templates, plan_content_series
from .diagnostics import format_diagnostics, run_diagnostics
from .edl import export_selection_file
from .inventory import build_inventory, write_inventory_outputs
from .modules import (
    disable_module,
    enable_module,
    module_rows,
    require_module_enabled,
    run_module_diagnostics,
    scaffold_module,
)
from .operations import default_registry, op_extract_segments
from .pipeline import available_presets, load_pipeline, plan_pipeline, run_pipeline, validate_pipeline, write_preset
from .rating import run_rating
from .review import assemble, create_approval_file, generate_review_assets
from .scaffold import PROJECT_TYPES, scaffold_project


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
    export_edl.add_argument("--fps", type=float, default=None)
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
    init.add_argument("preset", choices=sorted(available_presets()))
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

    calibrate = sub.add_parser("calibrate", help="Evaluate and tune footage scoring against annotations")
    calibrate_sub = calibrate.add_subparsers(dest="calibrate_command", required=True)
    calibrate_init = calibrate_sub.add_parser("init", help="Write a starter annotation JSON file")
    calibrate_init.add_argument("--output", "-o", required=True)
    calibrate_init.add_argument("--project", default="Videoedit Calibration")
    calibrate_init.add_argument("--source-root", default="footage/")
    calibrate_init.set_defaults(func=cmd_calibrate_init)
    calibrate_evaluate = calibrate_sub.add_parser("evaluate", help="Evaluate ratings.json against annotation JSON")
    calibrate_evaluate.add_argument("ratings")
    calibrate_evaluate.add_argument("--annotations", required=True)
    calibrate_evaluate.add_argument("--output", "-o", required=True)
    calibrate_evaluate.set_defaults(func=cmd_calibrate_evaluate)
    calibrate_tune = calibrate_sub.add_parser("tune", help="Write proposed scoring config candidates")
    calibrate_tune.add_argument("ratings")
    calibrate_tune.add_argument("--annotations", required=True)
    calibrate_tune.add_argument("--output", "-o", required=True)
    calibrate_tune.set_defaults(func=cmd_calibrate_tune)

    assemble_cmd = sub.add_parser("assemble", help="Assemble a rough cut from selection or approved JSON")
    assemble_cmd.add_argument("selection")
    assemble_cmd.add_argument("--output", "-o", required=True)
    assemble_cmd.set_defaults(func=cmd_assemble)

    captions = sub.add_parser("captions", help="Caption utilities")
    captions_sub = captions.add_subparsers(dest="caption_command", required=True)
    caption_styles = captions_sub.add_parser("styles", help="List caption styles")
    caption_styles.set_defaults(func=cmd_caption_styles)

    burn = sub.add_parser("burn-captions", help="Burn styled captions into a video")
    burn.add_argument("input")
    burn.add_argument("subtitles")
    burn.add_argument("--output", "-o", required=True)
    burn.add_argument("--style", default="automotive_racing")
    burn.add_argument("--format", default="original", choices=["original", "reel", "youtube"])
    burn.set_defaults(func=cmd_burn_captions)

    series = sub.add_parser("series", help="Plan reusable content series from ratings")
    series.add_argument("ratings", nargs="?", help="ratings.json, or 'templates' to list templates")
    series.add_argument("--template", default="team_tuesday")
    series.add_argument("--output", "-o")
    series.add_argument("--max-clips", type=int, default=5)
    series.set_defaults(func=cmd_series)

    content_map = sub.add_parser("content-map", help="Generate a ranked editorial content map")
    content_map.add_argument("ratings")
    content_map.add_argument("--output", "-o", required=True)
    content_map.set_defaults(func=cmd_content_map)

    quote_mining = sub.add_parser("quote-mining", help="Generate transcript-forward quote-mining report")
    quote_mining.add_argument("ratings")
    quote_mining.add_argument("--output", "-o", required=True)
    quote_mining.set_defaults(func=cmd_quote_mining)

    project = sub.add_parser("init-project", help="Create a video project folder scaffold")
    project.add_argument("name")
    project.add_argument("--type", choices=sorted(PROJECT_TYPES), default="reel")
    project.add_argument("--output", "-o", default=".")
    project.add_argument("--source")
    project.add_argument("--team-config")
    project.set_defaults(func=cmd_init_project)

    modules = sub.add_parser("modules", help="List, enable, disable, diagnose, and scaffold feature modules")
    modules_sub = modules.add_subparsers(dest="modules_command", required=True)
    modules_list = modules_sub.add_parser("list", help="List feature modules")
    modules_list.add_argument("--json", action="store_true")
    modules_list.set_defaults(func=cmd_modules_list)
    modules_enable = modules_sub.add_parser("enable", help="Enable an optional module in .videoedit/config.json")
    modules_enable.add_argument("module")
    modules_enable.set_defaults(func=cmd_modules_enable)
    modules_disable = modules_sub.add_parser("disable", help="Disable an optional module in .videoedit/config.json")
    modules_disable.add_argument("module")
    modules_disable.set_defaults(func=cmd_modules_disable)
    modules_doctor = modules_sub.add_parser("doctor", help="Check module availability and optional dependencies")
    modules_doctor.add_argument("--json", action="store_true")
    modules_doctor.set_defaults(func=cmd_modules_doctor)
    modules_scaffold = modules_sub.add_parser("scaffold", help="Scaffold a community module package")
    modules_scaffold.add_argument("name")
    modules_scaffold.add_argument("--output", "-o", required=True)
    modules_scaffold.set_defaults(func=cmd_modules_scaffold)

    return parser


def add_rate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("footage")
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--config")
    parser.add_argument("--transcript", choices=["off", "auto", "required"], default=None)
    parser.add_argument("--transcript-dir")
    parser.add_argument("--visual-objects", help="visual_objects.json from detect_visual_objects")
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
    if args.visual_objects:
        config.visual_objects_path = args.visual_objects
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
    require_module_enabled("core.inventory")
    items = build_inventory(args.footage)
    write_inventory_outputs(items, os.path.join(args.output, "inventory"))
    print(f"Inventory written to {args.output}")
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    require_module_enabled("core.rating")
    report = run_rating(args.footage, args.output, config=config_from_args(args))
    print(json.dumps(report.summary, indent=2))
    return 0


def cmd_export_edl(args: argparse.Namespace) -> int:
    require_module_enabled("core.handoff")
    output = args.output
    written = []
    for value in args.selections:
        paths = _expand_paths(value)
        for path in paths:
            written.extend(export_selection_file(path, output, fps=args.fps))
    print(f"Wrote {len(written)} handoff files to {output}")
    return 0


def cmd_extract_segments(args: argparse.Namespace) -> int:
    require_module_enabled("core.handoff")
    written = []
    for value in args.selections:
        result = op_extract_segments({}, {"input": value, "output": args.output})
        written.extend(result["files"])
    print(json.dumps({"output": args.output, "files": written}, indent=2))
    return 0


def cmd_review_assets(args: argparse.Namespace) -> int:
    require_module_enabled("core.review")
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
    require_module_enabled("core.review")
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
        print(f"{operation.name:28} {operation.module:22} {operation.description}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_diagnostics()
    report["modules"] = run_module_diagnostics()["modules"]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_diagnostics(report))
        print("")
        print("modules:")
        for row in report["modules"]:
            status = "enabled" if row["enabled"] else "disabled"
            if not row["available"]:
                status = "unavailable"
            print(f"  {status:11} {row['id']} - {row['description']}")
    return 0 if report["status"] == "ok" else 1


def cmd_calibrate_init(args: argparse.Namespace) -> int:
    require_module_enabled("core.calibration")
    output = init_annotation_file(args.output, project=args.project, source_root=args.source_root)
    print(f"Annotation template written to {output}")
    return 0


def cmd_calibrate_evaluate(args: argparse.Namespace) -> int:
    require_module_enabled("core.calibration")
    result = evaluate_ratings(args.ratings, args.annotations, args.output)
    print(json.dumps(result, indent=2))
    return 0


def cmd_calibrate_tune(args: argparse.Namespace) -> int:
    require_module_enabled("core.calibration")
    result = tune_scoring(args.ratings, args.annotations, args.output)
    print(json.dumps(result, indent=2))
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    require_module_enabled("core.review")
    output = assemble(args.selection, args.output)
    print(f"Rough cut written to {output}")
    return 0


def cmd_caption_styles(args: argparse.Namespace) -> int:
    require_module_enabled("delivery.captions")
    for item in list_caption_styles():
        print(f"{item['name']:20} {item['font']} {item['fontsize']}px")
    return 0


def cmd_burn_captions(args: argparse.Namespace) -> int:
    require_module_enabled("delivery.captions")
    output = burn_captions(args.input, args.subtitles, args.output, style=args.style, format_type=args.format)
    print(f"Captioned video written to {output}")
    return 0


def cmd_series(args: argparse.Namespace) -> int:
    require_module_enabled("content.series")
    if args.ratings == "templates":
        for template in list_series_templates():
            print(f"{template['id']:24} {template['name']} - {template['description']}")
        return 0
    if not args.ratings:
        raise ValueError("ratings.json is required, or use `videoedit series templates`")
    if not args.output:
        raise ValueError("--output is required")
    result = plan_content_series(args.ratings, args.output, template=args.template, max_clips=args.max_clips)
    print(json.dumps(result, indent=2))
    return 0


def cmd_content_map(args: argparse.Namespace) -> int:
    require_module_enabled("content.reports")
    result = generate_content_map(args.ratings, args.output)
    print(json.dumps(result, indent=2))
    return 0


def cmd_quote_mining(args: argparse.Namespace) -> int:
    require_module_enabled("content.reports")
    result = generate_quote_mining(args.ratings, args.output)
    print(json.dumps(result, indent=2))
    return 0


def cmd_init_project(args: argparse.Namespace) -> int:
    require_module_enabled("project.scaffold")
    result = scaffold_project(
        args.name,
        args.output,
        project_type=args.type,
        source=args.source,
        team_config=args.team_config,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_modules_list(args: argparse.Namespace) -> int:
    rows = module_rows()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        status = "enabled" if row["enabled"] else "disabled"
        if not row["available"]:
            status = "unavailable"
        core = "core" if row["core"] else "optional"
        print(f"{row['id']:24} {status:11} {core:8} {row['description']}")
    return 0


def cmd_modules_enable(args: argparse.Namespace) -> int:
    path = enable_module(args.module)
    print(f"Enabled module {args.module} in {path}")
    return 0


def cmd_modules_disable(args: argparse.Namespace) -> int:
    path = disable_module(args.module)
    print(f"Disabled module {args.module} in {path}")
    return 0


def cmd_modules_doctor(args: argparse.Namespace) -> int:
    report = run_module_diagnostics()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for row in report["modules"]:
        status = "enabled" if row["enabled"] else "disabled"
        if not row["available"]:
            status = "unavailable"
        print(f"{row['id']:24} {status:11} {row['description']}")
        for group in report["checks"]:
            if group["module"] != row["id"]:
                continue
            for check in group["checks"]:
                marker = "ok" if check["available"] else "missing"
                print(f"  {marker:7} {check['name']}")
    return 0


def cmd_modules_scaffold(args: argparse.Namespace) -> int:
    files = scaffold_module(args.name, args.output)
    print(json.dumps(files, indent=2))
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

"""
CLI - Command-line interface for videoedit.

Usage:
    videoedit run pipeline.yaml --input footage.mp4
    videoedit init preset/reel --output my_pipeline.yaml
    videoedit operations
    videoedit validate pipeline.yaml
"""
import sys
from pathlib import Path

import click
import yaml


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """videoedit - AI-first video editing pipeline system."""
    pass


@cli.command()
@click.argument("pipeline_file")
@click.option("--input", "-i", "input_file", required=True,
              help="Input video file")
@click.option("--output", "-o", "output_dir", help="Output directory (default: ./output)")
@click.option("--work-dir", help="Working directory for intermediates")
def run(pipeline_file, input_file, output_dir, work_dir):
    """Run a pipeline from a YAML file."""
    from .pipeline import Pipeline, Runner

    pipeline_file = Path(pipeline_file)
    input_file = Path(input_file)

    with open(pipeline_file) as f:
        data = yaml.safe_load(f)

    pipeline = Pipeline.from_dict(data)
    runner = Runner(pipeline, work_dir=work_dir)

    click.echo(f"Running pipeline: {pipeline.name}")
    click.echo(f"Input: {input_file}")
    click.echo(f"Steps: {len(pipeline.steps)}")

    try:
        result = runner.run(input_file, output_dir)
        click.echo("\n✓ Pipeline complete")
    except Exception as e:
        click.echo(f"\n✗ Pipeline failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("preset")
@click.option("--output", "-o", "output_file", required=True,
              help="Output pipeline file")
def init(preset, output_file):
    """Generate a pipeline from a preset."""
    from .presets import PRESETS

    output_file = Path(output_file)

    if preset not in PRESETS:
        available = ", ".join(PRESETS.keys())
        click.echo(f"Unknown preset: {preset}", err=True)
        click.echo(f"Available: {available}")
        sys.exit(1)

    preset_data = PRESETS[preset]
    with open(output_file, "w") as f:
        yaml.dump(preset_data, f, default_flow_style=False)

    click.echo(f"Created pipeline: {output_file}")
    click.echo(f"Preset: {preset}")


@cli.command()
def operations():
    """List available operations."""
    # Core operations (implemented as modules)
    ops = [
        ("transcribe_whisper", "Transcribe video with Whisper AI"),
        ("detect_highlights_audio", "Find highlights via audio spike detection"),
        ("detect_highlights_transcript", "Find highlights via transcript analysis"),
        ("extract_segments", "Extract clips from timestamps"),
        ("format_video", "Resize, crop, or pad video"),
        ("burn_captions", "Burn subtitles into video"),
        ("generate_edl", "Create EDL for DaVinci Resolve"),
        ("concatenate_videos", "Combine multiple video clips"),
        ("add_crossfades", "Add crossfade transitions between clips"),
        ("simple_crossfade", "Crossfade between two clips"),
        ("normalize_audio", "Normalize audio to target loudness"),
    ]

    click.echo("Available operations:\n")
    for name, desc in ops:
        click.echo(f"  {name:30} {desc}")


@cli.command()
def tui():
    """Launch the terminal UI."""
    from .tui.app import VideoEditApp

    app = VideoEditApp()
    app.run()


@cli.command()
@click.argument("pipeline_file")
def validate(pipeline_file):
    """Validate a pipeline YAML file."""
    from .pipeline import Pipeline

    with open(pipeline_file) as f:
        data = yaml.safe_load(f)

    try:
        pipeline = Pipeline.from_dict(data)
        click.echo(f"✓ Valid pipeline: {pipeline.name}")
        click.echo(f"  Steps: {len(pipeline.steps)}")
        for step in pipeline.steps:
            click.echo(f"    - {step.name} ({step.operation})")
    except Exception as e:
        click.echo(f"✗ Invalid pipeline: {e}", err=True)
        sys.exit(1)


def main():
    """Entry point for videoedit CLI."""
    cli()


if __name__ == "__main__":
    main()

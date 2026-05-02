"""
Transcribe operation - Whisper speech-to-text.

Transcribes video/audio files using OpenAI's Whisper model.
Outputs SRT and VTT subtitle files.
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from .base import BaseOperation, OperationResult


class TranscribeWhisper(BaseOperation):
    """
    Transcribe video using Whisper AI.

    Supports multiple model sizes and languages. Outputs SRT/VTT files.
    """

    name = "transcribe_whisper"
    description = "Transcribe video with Whisper AI"
    inputs = ["video", "audio"]
    outputs = ["srt", "vtt", "json"]

    # Whisper model options
    MODELS = ["tiny", "base", "small", "medium", "large", "large-v1", "large-v2", "large-v3"]

    def __init__(
        self,
        model: str = "small",
        language: str = "auto",
        task: str = "transcribe",
        output_format: str = "srt"
    ):
        """
        Initialize transcribe operation.

        Args:
            model: Whisper model size (tiny, base, small, medium, large)
            language: Language code or 'auto' for auto-detect
            task: 'transcribe' or 'translate' (to English)
            output_format: 'srt', 'vtt', 'json', or 'all'
        """
        super().__init__()
        self.model = model
        self.language = language
        self.task = task
        self.output_format = output_format

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute transcription."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Try using Whisper Python package first
        try:
            return self._transcribe_with_package(input_path, output_dir)
        except ImportError:
            # Fall back to CLI
            return self._transcribe_with_cli(input_path, output_dir)

    def _transcribe_with_package(self, input_path: Path, output_dir: Path) -> OperationResult:
        """Transcribe using whisper Python package."""
        import whisper

        click.echo(f"Loading Whisper model: {self.model}")
        model = whisper.load_model(self.model)

        click.echo(f"Transcribing: {input_path.name}")
        result = model.transcribe(
            str(input_path),
            language=None if self.language == "auto" else self.language,
            task=self.task
        )

        output_files = {}

        # Write SRT
        if self.output_format in ("srt", "all"):
            srt_file = output_dir / f"{input_path.stem}.srt"
            srt_content = self._to_srt(result["segments"])
            srt_file.write_text(srt_content, encoding="utf-8")
            output_files["srt"] = str(srt_file)

        # Write VTT
        if self.output_format in ("vtt", "all"):
            vtt_file = output_dir / f"{input_path.stem}.vtt"
            vtt_content = self._to_vtt(result["segments"])
            vtt_file.write_text(vtt_content, encoding="utf-8")
            output_files["vtt"] = str(vtt_file)

        # Write JSON
        if self.output_format in ("json", "all"):
            json_file = output_dir / f"{input_path.stem}_transcript.json"
            json_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            output_files["json"] = str(json_file)

        return OperationResult(
            success=True,
            output_path=Path(output_files.get("srt", list(output_files.values())[0])),
            data={
                **output_files,
                "language": result.get("language"),
                "duration": result.get("segments", [{}])[-1].get("end", 0) if result.get("segments") else 0,
                "text": result.get("text", "")
            }
        )

    def _transcribe_with_cli(self, input_path: Path, output_dir: Path) -> OperationResult:
        """Transcribe using whisper CLI."""
        output_file = output_dir / f"{input_path.stem}.{self.output_format}"

        cmd = [
            "whisper",
            str(input_path),
            "--model", self.model,
            "--output_dir", str(output_dir),
            "--output_format", self.output_format
        ]

        if self.language != "auto":
            cmd.extend(["--language", self.language])

        if self.task == "translate":
            cmd.append("--task translate")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode != 0:
            return OperationResult(
                success=False,
                error=f"Whisper CLI failed: {result.stderr}"
            )

        # Find the output file (whisper may add language suffix)
        for ext in ["srt", "vtt", "json"]:
            candidate = output_dir / f"{input_path.stem}.{ext}"
            if candidate.exists():
                return OperationResult(
                    success=True,
                    output_path=candidate,
                    data={"transcript_file": str(candidate)}
                )

        return OperationResult(
            success=False,
            error="Whisper CLI completed but output file not found"
        )

    def _to_srt(self, segments: list) -> str:
        """Convert segments to SRT format."""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp(seg["start"])
            end = self._format_timestamp(seg["end"])
            text = seg["text"].strip()
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        return "\n".join(lines)

    def _to_vtt(self, segments: list) -> str:
        """Convert segments to WebVTT format."""
        lines = ["WEBVTT\n"]
        for seg in segments:
            start = self._format_timestamp(seg["end"], vtt=True)
            end = self._format_timestamp(seg["end"], vtt=True)
            text = seg["text"].strip()
            lines.append(f"\n{start} --> {end}\n{text}")
        return "\n".join(lines)

    def _format_timestamp(self, seconds: float, vtt: bool = False) -> str:
        """Format seconds to SRT/VTT timestamp."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        separator = "." if vtt else ","
        return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03d}"


def main():
    """CLI for testing transcription."""
    import argparse

    parser = argparse.ArgumentParser(description="Transcribe with Whisper")
    parser.add_argument("input", help="Input video/audio file")
    parser.add_argument("--model", default="small", choices=TranscribeWhisper.MODELS)
    parser.add_argument("--language", default="auto", help="Language code")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory")

    args = parser.parse_args()

    op = TranscribeWhisper(
        model=args.model,
        language=args.language
    )

    result = op.execute(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        context={}
    )

    if result.success:
        print(f"Transcribed: {result.output_path}")
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Eleven Labs Text-to-Speech Integration
Generate AI voiceovers from text files or transcripts

Requirements:
    pip install elevenlabs python-dotenv

API Key: Get from https://elevenlabs.io/app/settings/api-keys
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional

try:
    from dotenv import load_dotenv
    from elevenlabs.client import ElevenLabs
    from elevenlabs import Voice, VoiceSettings
except ImportError:
    print("Required packages not found. Install with:")
    print("  pip install elevenlabs python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Popular voice IDs (browse more at https://elevenlabs.io/app/voice-library)
VOICES = {
    "george": "JBFqnCBsd6RMkjVDRZzb",      # Male, deep, narrator
    "rachel": "21m00Tcm4TlvDq8ikWAM",     # Female, clear, professional
    "josh": "TxGEqnHWrfWFTfGW9XjX",        # Male, casual, friendly
    "eleven": "XB0fDKeXKJhLQrrcTVCa5",     # Multi-purpose, balanced
    "adam": "pNInz6obpgD5QxJI6g950",      # Male, energetic
    "fin": "MF3mGyEgrCl72SYkWv0kO",       # Male, story-telling
    "clyde": "2EiwWnXFnvUQLJ3g6VcuWF",    # Male, deep, authoritative
    "dori": "UZpHnEqLHPiSPxNARouh",       # Female, warm, friendly
    "patrick": "x2xQ8hLqYjqHGhOLxUZEN",   # Male, professional, calm
    "sarah": "EXAVITQuvMyVWVLlhTwmv",     # Female, energetic, upbeat
}


class VoiceoverGenerator:
    """Generate AI voiceovers using Eleven Labs API"""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Eleven Labs client

        Args:
            api_key: Eleven Labs API key (or from ELEVENLABS_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY not found. "
                "Set environment variable or pass api_key parameter.\n"
                "Get API key from: https://elevenlabs.io/app/settings/api-keys"
            )

        self.client = ElevenLabs(api_key=self.api_key)

    def list_available_voices(self) -> List[Voice]:
        """Get list of all available voices"""
        voices = self.client.voices.get_all()
        return voices

    def generate(
        self,
        text: str,
        output_file: str,
        voice_id: str = "JBFqnCBsd6RMkjVDRZzb",
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128"
    ) -> str:
        """Generate TTS from text

        Args:
            text: Text to convert to speech
            output_file: Output MP3 file path
            voice_id: Eleven Labs voice ID (default: George)
            model_id: Model to use (eleven_v3, eleven_multilingual_v2, etc.)
            output_format: Audio format (mp3_44100_128, mp3_44100_192, pcm_16000)

        Returns:
            Path to generated audio file
        """
        print(f"Generating voiceover: {len(text)} chars using voice {voice_id}")

        audio = self.client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format
        )

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'wb') as f:
            f.write(audio)

        print(f"Voiceover saved: {output_path}")
        return str(output_path)

    def from_srt(
        self,
        srt_file: str,
        output_file: str,
        voice_id: str = "JBFqnCBsd6RMkjVDRZzb",
        combine: bool = True
    ) -> str:
        """Generate voiceover from SRT transcript

        Args:
            srt_file: Path to SRT subtitle file
            output_file: Output MP3 file path
            voice_id: Voice ID to use
            combine: If True, combine all segments into one audio file

        Returns:
            Path to generated audio file
        """
        srt_path = Path(srt_file)
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_file}")

        # Parse SRT file
        with open(srt_path, 'r') as f:
            srt_content = f.read()

        # Extract text segments with timing
        pattern = r'(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n*$)'
        matches = re.findall(pattern, srt_content, re.DOTALL)

        if not matches:
            raise ValueError(f"No subtitle entries found in {srt_file}")

        # Combine all text
        full_text = " ".join([match[10].strip() for match in matches])

        print(f"Extracted {len(matches)} subtitle entries from {srt_file}")
        print(f"Total text length: {len(full_text)} characters")

        return self.generate(full_text, output_file, voice_id)

    def from_txt(self, txt_file: str, output_file: str, **kwargs) -> str:
        """Generate voiceover from plain text file

        Args:
            txt_file: Path to text file
            output_file: Output MP3 file path
            **kwargs: Passed to generate()

        Returns:
            Path to generated audio file
        """
        txt_path = Path(txt_file)
        if not txt_path.exists():
            raise FileNotFoundError(f"Text file not found: {txt_file}")

        with open(txt_path, 'r') as f:
            text = f.read().strip()

        if not text:
            raise ValueError(f"Text file is empty: {txt_file}")

        return self.generate(text, output_file, **kwargs)


def show_voices():
    """Display available voice presets"""
    print("Available voice presets:")
    for name, voice_id in VOICES.items():
        print(f"  {name:12} : {voice_id}")
    print("\nBrowse all voices at: https://elevenlabs.io/app/voice-library")


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI voiceovers using Eleven Labs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from text
  python voiceover.py --text "Welcome to Drive Auto Sports" --output intro.mp3

  # Generate from SRT transcript
  python voiceover.py --srt transcript.srt --output narration.mp3

  # Generate from text file
  python voiceover.py --txt script.txt --output voiceover.mp3 --voice rachel

  # List voice presets
  python voiceover.py --list-voices

Voice presets:
  george    - Male, deep, narrator (default)
  rachel    - Female, clear, professional
  josh      - Male, casual, friendly
  eleven    - Multi-purpose, balanced
  adam      - Male, energetic
  fin       - Male, story-telling
  clyde     - Male, deep, authoritative
  dori      - Female, warm, friendly
  patrick   - Male, professional, calm
  sarah     - Female, energetic, upbeat
        """
    )

    # Input sources (one required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", "-t", help="Text to convert to speech")
    input_group.add_argument("--srt", "-s", help="SRT subtitle file")
    input_group.add_argument("--txt", "-f", help="Plain text file")

    # Output
    parser.add_argument("--output", "-o", required=True, help="Output MP3 file")

    # Voice options
    parser.add_argument("--voice", "-v", default="george",
                       choices=list(VOICES.keys()),
                       help="Voice preset (default: george)")
    parser.add_argument("--voice-id", help="Custom voice ID (overrides --voice)")
    parser.add_argument("--model", default="eleven_multilingual_v2",
                       help="Model ID (default: eleven_multilingual_v2)")
    parser.add_argument("--format", default="mp3_44100_128",
                       help="Output format (default: mp3_44100_128)")

    # Utility
    parser.add_argument("--list-voices", action="store_true",
                       help="List available voice presets")

    args = parser.parse_args()

    if args.list_voices:
        show_voices()
        return

    # Get voice ID
    voice_id = args.voice_id or VOICES[args.voice]

    # Create generator
    try:
        generator = VoiceoverGenerator()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Generate voiceover
    try:
        if args.text:
            generator.generate(
                text=args.text,
                output_file=args.output,
                voice_id=voice_id,
                model_id=args.model,
                output_format=args.format
            )
        elif args.srt:
            generator.from_srt(
                srt_file=args.srt,
                output_file=args.output,
                voice_id=voice_id
            )
        elif args.txt:
            generator.from_txt(
                txt_file=args.txt,
                output_file=args.output,
                voice_id=voice_id,
                model_id=args.model,
                output_format=args.format
            )
    except Exception as e:
        print(f"Error generating voiceover: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

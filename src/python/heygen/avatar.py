#!/usr/bin/env python3
"""
HeyGen Avatar Video Generation
Create AI avatar videos for intros, hosting segments

Requirements:
    pip install requests python-dotenv

API Key: Get from https://dashboard.heygen.com/settings
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    import requests
except ImportError:
    print("Required packages not found. Install with:")
    print("  pip install requests python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Popular avatar IDs (browse more at https://heygen.com/avatar-library)
AVATARS = {
    "anna": "Anna-public-1-1_20230708",
    "josh": "josh-3-public_20220721",
    "mia": "Mia-public-1_20221025",
    "elena": "elena_d10_20240123",
    "katherine": "Katherine_S2_20220721",
    "charlotte": "charlotte_d1_20230606",
    "tyra": "Tyra_Johnson_v1_20230131",
    "martha": "Martha_v1_20230424",
    "patrick": "Patrick_public_1_20220629",
    "kuya": "Kuya_public_1_20220721",
}

# Voice options (Eleven Labs voices can also be used)
VOICES = {
    "jenny": "en-US-JennyNeural",
    "guy": "en-US-GuyNeural",
    "jane": "en-US-JaneNeural",
    "jason": "en-US-JasonNeural",
    "sara": "en-US-SaraNeural",
    "tony": "en-US-TonyNeural",
    "natalie": "en-US-NatalieNeural",
    "amir": "en-US-AmirNeural",
}


class HeyGenAvatar:
    """Generate AI avatar videos using HeyGen API"""

    BASE_URL = "https://api.heygen.com"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize HeyGen client

        Args:
            api_key: HeyGen API key (or from HEYGEN_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("HEYGEN_API_KEY")
        if not self.api_key:
            raise ValueError(
                "HEYGEN_API_KEY not found. "
                "Set environment variable or pass api_key parameter.\n"
                "Get API key from: https://dashboard.heygen.com/settings"
            )

        self.headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make API request with error handling"""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = requests.request(method, url, json=data, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")

    def list_avatars(self) -> List[Dict]:
        """Get list of available avatars"""
        result = self._request("GET", "/v1/avatars.list")
        return result.get("data", {}).get("avatars", [])

    def create_video(
        self,
        text: str,
        avatar_id: str = "Anna-public-1-1_20230708",
        voice_id: str = "en-US-JennyNeural",
        output_file: str = "avatar.mp4",
        quality: str = "medium",
        aspect_ratio: str = "16:9"
    ) -> str:
        """Generate avatar video from text

        Args:
            text: Script text for avatar to speak
            avatar_id: HeyGen avatar ID
            voice_id: Voice ID to use
            output_file: Output MP4 file path
            quality: Video quality (low, medium, high)
            aspect_ratio: Video aspect ratio (16:9, 9:16)

        Returns:
            Path to generated video file
        """
        print(f"Creating avatar video: {len(text)} chars")

        # Submit generation job
        response = self._request("POST", "/v1/videoing.create_video", {
            "text": text,
            "avatar_id": avatar_id,
            "voice_id": voice_id,
            "video_quality": quality,
            "aspect_ratio": aspect_ratio
        })

        video_id = response.get("data", {}).get("video_id")
        if not video_id:
            raise RuntimeError("Failed to create video job")

        print(f"Video ID: {video_id}")
        print("Waiting for generation...")

        # Poll for completion
        while True:
            status_data = self.check_status(video_id)
            status = status_data.get("status")

            if status == "completed":
                break
            elif status == "failed":
                error = status_data.get("error", "Unknown error")
                raise RuntimeError(f"Video generation failed: {error}")
            elif status in ("processing", "pending"):
                print(f"  Status: {status}...")
                time.sleep(10)
            else:
                raise RuntimeError(f"Unknown status: {status}")

        # Download video
        video_url = status_data.get("video_url")
        if not video_url:
            raise RuntimeError("No video URL in completed response")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Downloading to: {output_path}")
        video_data = requests.get(video_url).content
        with open(output_path, 'wb') as f:
            f.write(video_data)

        print(f"Avatar video saved: {output_path}")
        return str(output_path)

    def check_status(self, video_id: str) -> Dict:
        """Check video generation status"""
        result = self._request("GET", f"/v1/videoing.status?video_id={video_id}")
        return result.get("data", {})

    def from_txt(self, txt_file: str, **kwargs) -> str:
        """Generate avatar video from text file

        Args:
            txt_file: Path to text file
            **kwargs: Passed to create_video()

        Returns:
            Path to generated video file
        """
        txt_path = Path(txt_file)
        if not txt_path.exists():
            raise FileNotFoundError(f"Text file not found: {txt_file}")

        with open(txt_path, 'r') as f:
            text = f.read().strip()

        if not text:
            raise ValueError(f"Text file is empty: {txt_file}")

        return self.create_video(text, **kwargs)

    def from_srt(self, srt_file: str, output_dir: str = "avatar_clips", **kwargs) -> List[str]:
        """Generate avatar videos from SRT transcript

        Args:
            srt_file: Path to SRT subtitle file
            output_dir: Directory for output clips
            **kwargs: Passed to create_video()

        Returns:
            List of paths to generated video files
        """
        import re

        srt_path = Path(srt_file)
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_file}")

        with open(srt_path, 'r') as f:
            srt_content = f.read()

        # Parse SRT entries
        pattern = r'(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n*$)'
        matches = re.findall(pattern, srt_content, re.DOTALL)

        if not matches:
            raise ValueError(f"No subtitle entries found in {srt_file}")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        generated = []

        for i, match in enumerate(matches):
            text = match[10].strip()
            if not text:
                continue

            output_file = output_path / f"clip_{i+1:03d}.mp4"

            print(f"\nGenerating clip {i+1}/{len(matches)}")
            result = self.create_video(
                text=text,
                output_file=str(output_file),
                **kwargs
            )
            generated.append(result)

        print(f"\nGenerated {len(generated)} avatar clips")
        return generated


def show_avatars():
    """Display available avatar presets"""
    print("Available avatar presets:")
    for name, avatar_id in AVATARS.items():
        print(f"  {name:12} : {avatar_id}")
    print("\nBrowse all avatars at: https://heygen.com/avatar-library")


def show_voices():
    """Display available voice presets"""
    print("Available voice presets:")
    for name, voice_id in VOICES.items():
        print(f"  {name:12} : {voice_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI avatar videos using HeyGen",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from text
  python avatar.py --text "Welcome to Drive Auto Sports" --output intro.mp4

  # Generate from text file
  python avatar.py --txt script.txt --output intro.mp4 --avatar anna --voice jenny

  # Generate from SRT (multiple clips)
  python avatar.py --srt transcript.srt --output-dir avatar_clips/

  # List presets
  python avatar.py --list-avatars
  python avatar.py --list-voices

Avatar presets:
  anna       - Female, professional (default)
  josh       - Male, casual
  mia        - Female, friendly
  elena      - Female, energetic
  katherine  - Female, narrator
  charlotte - Female, warm
  tyra       - Female, confident
  martha     - Female, mature
  patrick    - Male, professional
  kuya       - Male, friendly

Voice presets:
  jenny    - Female, American (default)
  guy      - Male, American
  jane     - Female, American
  jason    - Male, American
  sara     - Female, American
  tony     - Male, American
  natalie  - Female, American
  amir     - Male, American
        """
    )

    # Input sources (one required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", "-t", help="Script text for avatar to speak")
    input_group.add_argument("--txt", "-f", help="Text file with script")
    input_group.add_argument("--srt", "-s", help="SRT subtitle file (generates multiple clips)")

    # Output
    parser.add_argument("--output", "-o", help="Output MP3 file (for single text/txt input)")
    parser.add_argument("--output-dir", "-d", default="avatar_clips",
                       help="Output directory for SRT clips (default: avatar_clips/)")

    # Avatar options
    parser.add_argument("--avatar", "-a", default="anna",
                       choices=list(AVATARS.keys()),
                       help="Avatar preset (default: anna)")
    parser.add_argument("--avatar-id", help="Custom avatar ID (overrides --avatar)")
    parser.add_argument("--voice", "-v", default="jenny",
                       choices=list(VOICES.keys()),
                       help="Voice preset (default: jenny)")
    parser.add_argument("--voice-id", help="Custom voice ID (overrides --voice)")
    parser.add_argument("--quality", "-q", default="medium",
                       choices=["low", "medium", "high"],
                       help="Video quality (default: medium)")
    parser.add_argument("--aspect", "-r", default="16:9",
                       choices=["16:9", "9:16"],
                       help="Aspect ratio (default: 16:9)")

    # Utility
    parser.add_argument("--list-avatars", action="store_true",
                       help="List available avatar presets")
    parser.add_argument("--list-voices", action="store_true",
                       help="List available voice presets")

    args = parser.parse_args()

    if args.list_avatars:
        show_avatars()
        return

    if args.list_voices:
        show_voices()
        return

    # Get IDs
    avatar_id = args.avatar_id or AVATARS[args.avatar]
    voice_id = args.voice_id or VOICES[args.voice]

    # Create generator
    try:
        generator = HeyGenAvatar()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Generate video
    try:
        if args.text:
            output = args.output or "avatar.mp4"
            generator.create_video(
                text=args.text,
                avatar_id=avatar_id,
                voice_id=voice_id,
                output_file=output,
                quality=args.quality,
                aspect_ratio=args.aspect
            )
        elif args.txt:
            output = args.output or "avatar.mp4"
            generator.from_txt(
                txt_file=args.txt,
                avatar_id=avatar_id,
                voice_id=voice_id,
                output_file=output,
                quality=args.quality,
                aspect_ratio=args.aspect
            )
        elif args.srt:
            generator.from_srt(
                srt_file=args.srt,
                output_dir=args.output_dir,
                avatar_id=avatar_id,
                voice_id=voice_id,
                quality=args.quality,
                aspect_ratio=args.aspect
            )
    except Exception as e:
        print(f"Error generating avatar video: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

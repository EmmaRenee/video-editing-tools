#!/usr/bin/env python3
"""
video-start - Interactive video project initializer

Guides through setting up a new video editing project with optional AI asset generation.
Generic version that can be used for any project/team.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add tools directory to path for imports (when used as part of a larger repo)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import cloud API tools (optional)
try:
    from tools.elevenlabs.voiceover import VoiceoverGenerator
    VOICEOVER_AVAILABLE = True
except ImportError:
    try:
        from python.elevenlabs.voiceover import VoiceoverGenerator
        VOICEOVER_AVAILABLE = True
    except ImportError:
        VOICEOVER_AVAILABLE = False

try:
    from tools.heygen.avatar import HeyGenAvatar
    AVATAR_AVAILABLE = True
except ImportError:
    try:
        from python.heygen.avatar import HeyGenAvatar
        AVATAR_AVAILABLE = True
    except ImportError:
        AVATAR_AVAILABLE = False

try:
    from tools.canva.design import LocalDesignGenerator
    CANVA_AVAILABLE = True
except ImportError:
    try:
        from python.canva.design import LocalDesignGenerator
        CANVA_AVAILABLE = True
    except ImportError:
        CANVA_AVAILABLE = False


PROJECT_TYPES = {
    "1": {"name": "reel", "description": "Instagram Reel (9:16 vertical)", "aspect": "9:16"},
    "2": {"name": "youtube", "description": "YouTube video (16:9 horizontal)", "aspect": "16:9"},
    "3": {"name": "documentary", "description": "Long-form documentary", "aspect": "16:9"},
    "4": {"name": "interview", "description": "Interview/Talking head", "aspect": "16:9"},
    "5": {"name": "broll", "description": "B-roll footage package", "aspect": "original"},
    "6": {"name": "podcast", "description": "Podcast/Audio content", "aspect": "original"},
    "7": {"name": "tutorial", "description": "Tutorial/How-to video", "aspect": "16:9"},
}


def load_team_config(config_path: str) -> List[Dict]:
    """Load team members from a JSON config file."""
    config_file = Path(config_path)
    if not config_file.exists():
        return []

    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
            return data.get('team_members', [])
    except (json.JSONDecodeError, IOError):
        return []


def get_input(prompt: str, default: str = "") -> str:
    """Get user input with optional default."""
    if default:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "

    result = input(full_prompt).strip()
    return result if result else default


def confirm(prompt: str) -> bool:
    """Ask yes/no confirmation."""
    while True:
        response = input(f"{prompt} (y/n): ").strip().lower()
        if response in ('y', 'yes'):
            return True
        elif response in ('n', 'no'):
            return False
        print("Please enter 'y' or 'n'")


def create_project_structure(project_path: Path, project_type: str) -> Dict:
    """Create standard project folder structure."""
    folders = {
        "raw": "Raw footage",
        "audio": "Audio files (music, SFX)",
        "exports": "Final exports",
        "assets": "Graphics, lower thirds, overlays",
        "scripts": "Scripts and transcripts",
        "drafts": "Work in progress edits",
    }

    created = {}
    for folder, description in folders.items():
        path = project_path / folder
        path.mkdir(parents=True, exist_ok=True)
        created[folder] = str(path)

    return created


def generate_workflow_config(
    project_path: Path,
    project_name: str,
    project_type: str,
    source_footage: str,
    options: Dict
) -> str:
    """Generate workflow config for automated workflows."""
    config = {
        "title": project_name,
        "project_type": project_type,
        "created": datetime.now().isoformat(),
        "source_footage": source_footage,
        "output": str(project_path / "exports"),
    }

    # Add AI options if selected
    if options.get("voiceover"):
        config["intro_script"] = options.get("intro_script", "")
        config["voiceover_script"] = options.get("voiceover_script", "")
        config["voice"] = options.get("voice", "george")

    if options.get("avatar"):
        config["avatar_intro"] = True
        config["avatar_text"] = options.get("avatar_text", "")
        config["avatar_id"] = options.get("avatar_id", "Anna-public-1-1_20230708")

    if options.get("graphics"):
        config["title_graphic"] = True
        config["lower_thirds"] = options.get("lower_thirds", [])

    config_file = project_path / "workflow_config.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    return str(config_file)


def create_readme(project_path: Path, project_name: str, details: Dict) -> str:
    """Create project README with workflow info."""
    readme_content = f"""# {project_name}

**Created:** {datetime.now().strftime('%Y-%m-%d')}
**Type:** {details.get('type', 'Unknown')}
**Source:** {details.get('source', 'N/A')}

## Project Structure

```
{project_path.name}/
├── raw/           # Raw footage
├── audio/         # Music, SFX
├── exports/       # Final exports
├── assets/        # Graphics, lower thirds
├── scripts/       # Scripts, transcripts
└── drafts/        # WIP edits
```

## Workflow

### 1. Import Footage
Copy raw footage to `raw/` folder

### 2. Generate Clips (Optional)
```bash
# Using Python inventory
python -m python.inventory "raw/"

# Or manually extract with FFmpeg
ffmpeg -i raw_footage.mp4 -ss 00:00:10 -to 00:00:30 -c copy clip.mp4
```

### 3. Create Rough Cut
- Use FFmpeg to extract highlights
- Or edit directly in your video editor
- Generate EDL if using DaVinci Resolve

### 4. Add AI Assets (Optional)
{f'- Voiceover: Generate with Eleven Labs or similar TTS' if details.get('voiceover') else ''}
{f"- Avatar intro: Generate with HeyGen or similar avatar service" if details.get('avatar') else ''}
{f"- Lower thirds: Create with Canva or similar design tool" if details.get('graphics') else ''}

### 5. Format for Output
```bash
# Instagram Reel (9:16)
ffmpeg -i clip.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" reel.mp4

# YouTube (16:9)
ffmpeg -i clip.mp4 -vf "scale=1920:1080" youtube.mp4
```

### 6. Export
- Export final version to `exports/`
- Format for your target platform

## Notes

{details.get('notes', '')}

---
Generated by video-start
"""

    readme_file = project_path / "README.md"
    with open(readme_file, 'w') as f:
        f.write(readme_content)

    return str(readme_file)


def create_team_config_template(project_path: Path) -> str:
    """Create a template team config file."""
    template = {
        "team_name": "Your Team/Company Name",
        "team_members": [
            {"name": "Person Name", "role": "Role/Title"},
            {"name": "Another Person", "role": "Another Role"},
        ]
    }

    config_file = project_path / "team_config.json"
    with open(config_file, 'w') as f:
        json.dump(template, f, indent=2)

    return str(config_file)


def interactive_setup(team_config: str = None) -> Dict:
    """Run interactive project setup."""
    print("=" * 60)
    print("VIDEO PROJECT INITIALIZER")
    print("=" * 60)
    print()

    # Project name
    project_name = get_input("Project name", "new_project")

    # Project type
    print("\nProject type:")
    for key, info in PROJECT_TYPES.items():
        print(f"  {key}. {info['description']}")
    type_choice = get_input("Select type", "1")
    project_type = PROJECT_TYPES.get(type_choice, PROJECT_TYPES["1"])

    # Source footage
    source_footage = get_input("\nSource footage location (absolute path or 'none')", "none")

    # Create project directory
    base_dir = Path.cwd()
    project_path = base_dir / project_name

    if project_path.exists():
        print(f"\nWarning: Project directory already exists: {project_path}")
        if not confirm("Continue and add to existing project?"):
            print("Cancelled.")
            sys.exit(0)

    print(f"\nCreating project at: {project_path}")
    folders = create_project_structure(project_path, project_type["name"])
    print("✓ Project structure created")

    # Load team config if provided
    team_members = []
    if team_config:
        team_members = load_team_config(team_config)
        if team_members:
            print(f"✓ Loaded {len(team_members)} team members from config")

    # AI asset options
    print("\n" + "-" * 60)
    print("AI ASSET GENERATION (Optional)")
    print("-" * 60)

    options = {
        "voiceover": False,
        "avatar": False,
        "graphics": False,
    }

    # Voiceover
    if VOICEOVER_AVAILABLE:
        if confirm("\nGenerate AI voiceover intro?"):
            options["voiceover"] = True
            options["intro_script"] = get_input("  Intro script", "Welcome to the show")
            options["voice"] = get_input("  Voice preset (george, rachel, josh, etc.)", "george")
    else:
        print("\nNote: Voiceover generation not available.")

    # Avatar
    if AVATAR_AVAILABLE:
        if confirm("\nGenerate AI avatar intro?"):
            options["avatar"] = True
            options["avatar_text"] = get_input("  Avatar script", "Welcome! Today we're looking at...")
    else:
        print("\nNote: Avatar generation not available.")

    # Graphics
    if CANVA_AVAILABLE or team_members:
        if confirm("\nGenerate motion graphics/lower thirds?"):
            options["graphics"] = True

            # Use loaded team members or prompt for config
            if team_members:
                print(f"  Using team from config: {len(team_members)} members")
                if confirm("  Generate lower thirds for all team members?"):
                    options["lower_thirds"] = team_members
            elif confirm("  Enter team members now?"):
                team_members = []
                print("  Enter team members (empty name to finish):")
                while True:
                    name = get_input(f"    Member {len(team_members) + 1} name", "")
                    if not name:
                        break
                    role = get_input(f"    {name}'s role", "Team Member")
                    team_members.append({"name": name, "role": role})

                if team_members:
                    options["lower_thirds"] = team_members

    # Generate files
    print("\n" + "-" * 60)
    print("GENERATING PROJECT FILES")
    print("-" * 60)

    # Workflow config
    workflow_config = generate_workflow_config(
        project_path, project_name, project_type["name"],
        source_footage, options
    )
    print(f"✓ Workflow config: {workflow_config}")

    # README
    readme_details = {
        "type": project_type["name"],
        "source": source_footage,
        "format": project_type["name"],
        "voiceover": options["voiceover"],
        "avatar": options["avatar"],
        "graphics": options["graphics"],
        "notes": "",
    }
    readme = create_readme(project_path, project_name, readme_details)
    print(f"✓ README: {readme}")

    # Team config template (if graphics selected and no config provided)
    if options.get("graphics") and not team_config:
        team_template = create_team_config_template(project_path)
        print(f"✓ Team config template: {team_template}")

    print("\n" + "=" * 60)
    print("PROJECT CREATED!")
    print("=" * 60)
    print(f"\nLocation: {project_path}")
    print(f"\nNext steps:")
    print(f"  1. Copy footage to: {folders['raw']}")
    print(f"  2. Edit team_config.json if needed")
    print(f"  3. Start editing!")

    return {
        "project_path": str(project_path),
        "project_name": project_name,
        "type": project_type["name"],
        "options": options,
    }


def quick_setup(project_name: str, project_type: str, source: str = "", team_config: str = None) -> Dict:
    """Non-interactive quick setup."""
    project_path = Path.cwd() / project_name
    type_info = PROJECT_TYPES.get(str(project_type), PROJECT_TYPES["1"])

    print(f"Creating '{project_name}' ({type_info['name']}) at: {project_path}")

    folders = create_project_structure(project_path, type_info["name"])
    print("✓ Project structure created")

    options = {"voiceover": False, "avatar": False, "graphics": False}

    # Load team if config provided
    if team_config:
        team_members = load_team_config(team_config)
        if team_members:
            options["graphics"] = True
            options["lower_thirds"] = team_members
            print(f"✓ Loaded {len(team_members)} team members")

    # Generate basic files
    workflow_config = generate_workflow_config(
        project_path, project_name, type_info["name"],
        source or "none", options
    )
    print(f"✓ Workflow config: {workflow_config}")

    readme_details = {
        "type": type_info["name"],
        "source": source or "N/A",
        "format": type_info["name"],
        "voiceover": False,
        "avatar": False,
        "graphics": options["graphics"],
        "notes": "Quick setup - run with --interactive for more options.",
    }
    readme = create_readme(project_path, project_name, readme_details)
    print(f"✓ README: {readme}")

    print(f"\nProject created: {project_path}")

    return {
        "project_path": str(project_path),
        "project_name": project_name,
        "type": type_info["name"],
        "options": options,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Interactive video project initializer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive setup (recommended)
  python video_start.py --interactive

  # Quick setup
  python video_start.py my_reel_project --type reel

  # Quick setup with source footage
  python video_start.py transmission_build --type youtube --source /path/to/footage

  # With team config
  python video_start.py interview --type interview --team-config team.json

  # Documentary project
  python video_start.py "Day at the Shop" --type documentary
        """
    )

    parser.add_argument("name", nargs="?",
                       help="Project name (required for non-interactive)")
    parser.add_argument("--type", "-t",
                       choices=["reel", "youtube", "documentary", "interview", "broll", "podcast", "tutorial"],
                       help="Project type")
    parser.add_argument("--source", "-s",
                       help="Source footage location")
    parser.add_argument("--team-config", "-tc",
                       help="Path to team_config.json file for lower thirds")
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="Interactive mode with prompts")
    parser.add_argument("--list-types", action="store_true",
                       help="List available project types")

    args = parser.parse_args()

    if args.list_types:
        print("Available project types:")
        for key, info in PROJECT_TYPES.items():
            print(f"  {info['name']:12} - {info['description']}")
        return

    if args.interactive:
        result = interactive_setup(args.team_config)
    else:
        if not args.name:
            parser.error("name required (or use --interactive)")
        if not args.type:
            parser.error("--type required (or use --interactive)")

        result = quick_setup(args.name, args.type, args.source or "", args.team_config)

    # Save session info
    session_file = Path.cwd() / ".video-start-last.json"
    with open(session_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "result": result
        }, f, indent=2)
    print(f"\nSession info saved to: {session_file}")


if __name__ == "__main__":
    main()

# Install Guide

Canonical setup for the Video Editing Tools repository, the `videoedit` Python package, YOLO/advanced detectors, PowerShell helpers, and the portable editing skill.

## What Gets Installed

| Layer | Required | Purpose |
|-------|----------|---------|
| FFmpeg + ffprobe | Yes | Metadata, signal analysis, clip extraction, rough-cut assembly |
| Python 3.12 virtual environment | Yes for `videoedit` | Local package, CLI, YAML pipelines, review assets |
| `videoedit` package | Yes for automation | Inventory, rating, selections, EDL/XML/M3U, rough cuts |
| Whisper | Optional | Transcript signals and captions |
| Tesseract | Optional | OCR/signage detection |
| YOLO / Ultralytics | Optional | Visual object detection through `detect_visual_objects` |
| OpenCV | Optional | Face/person presence detection |
| PowerShell module | Optional | Windows-friendly FFmpeg helper cmdlets |
| DaVinci Resolve | Optional | Final polish after generated handoff files |

The deterministic pipeline works with only Python, FFmpeg, and ffprobe. Install YOLO and other advanced providers only when you need those signal artifacts.

## macOS Setup

Install base tools:

```bash
brew install ffmpeg tesseract python@3.12
```

Create the repo-local virtual environment from the repository root:

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Install the core package:

```bash
python -m pip install -e ./src/python
```

Install the full local pipeline with Whisper, OpenCV, and YOLO/Ultralytics:

```bash
python -m pip install -e "./src/python[whisper,advanced]"
```

Optional extras:

```bash
python -m pip install -e "./src/python[ui]"
python -m pip install -e "./src/python[cloud]"
```

Activate this environment before running repository commands:

```bash
source .venv/bin/activate
```

## Windows Setup

Install system tools:

```powershell
winget install Gyan.FFmpeg
winget install Python.Python.3.12
winget install UB-Mannheim.TesseractOCR
```

Create and activate the virtual environment from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .\src\python
python -m pip install -e ".\src\python[whisper,advanced]"
```

If PowerShell blocks activation scripts:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Install the optional PowerShell helper module:

```powershell
$modulePath = "$HOME\Documents\PowerShell\Modules\VideoEditing"
New-Item -ItemType Directory -Path $modulePath -Force
Copy-Item src\powershell\VideoEditing.psm1 $modulePath\VideoEditing.psm1 -Force
Import-Module VideoEditing
```

## Linux Setup

Install base tools:

```bash
sudo apt update
sudo apt install ffmpeg tesseract-ocr python3.12 python3.12-venv python3-pip
```

Create and activate the virtual environment from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ./src/python
python -m pip install -e "./src/python[whisper,advanced]"
```

If Python 3.12 is not available from your distribution packages, install Python 3.12 with `pyenv`, your distribution backports, or the official Python installer before creating `.venv`.

## Verify Installation

From the repository root with the virtual environment active:

```bash
python --version
python -m pip show videoedit ultralytics opencv-python openai-whisper
command -v videoedit
command -v yolo
videoedit doctor
videoedit operations
yolo checks
```

Expected `videoedit doctor` result:

- Required `ffmpeg` and `ffprobe` are `ok`.
- Optional `whisper`, `tesseract`, `yolo`, and `cv2` are `ok` when full extras are installed.

Optional YOLO smoke test outside the repository:

```bash
mkdir -p /tmp/videoedit-yolo-smoke
cd /tmp/videoedit-yolo-smoke
yolo predict model=yolo26n.pt source=https://ultralytics.com/images/bus.jpg project=/tmp/videoedit-yolo-smoke name=predict exist_ok=True
```

The first YOLO run downloads model weights. Keep YOLO `runs/` output outside the repo or rely on `.gitignore`.

## Use The Pipeline

Inventory and rate footage:

```bash
videoedit inventory footage/ --output analysis/
videoedit rate footage/ --output analysis/
```

Review and approve candidates:

```bash
videoedit review-assets analysis/ratings.json --output review/
videoedit approve analysis/ratings.json --output approved.json --decisions review/review_decisions.json
```

Assemble and export handoff files:

```bash
videoedit assemble approved.json --output rough_cut.mp4
videoedit extract-segments approved.json --output clips/
videoedit export-edl approved.json --output edl/
```

Preset pipelines:

```bash
videoedit init roughcut --output roughcut.yaml
videoedit validate roughcut.yaml
videoedit plan roughcut.yaml --input footage/ --output output/
videoedit run roughcut.yaml --input footage/ --output output/ --dry-run
videoedit run roughcut.yaml --input footage/ --output output/
```

YOLO is used by the `detect_visual_objects` operation when the `yolo` command is available.

## Install The Skill

Claude-style local skill:

```bash
mkdir -p ~/.claude/skills/video-editing
cp src/SKILL.md ~/.claude/skills/video-editing/SKILL.md
```

Codex-style local skill:

```bash
mkdir -p ~/.codex/skills/video-editing
cp src/SKILL.md ~/.codex/skills/video-editing/SKILL.md
```

Windows PowerShell equivalents:

```powershell
New-Item -ItemType Directory -Path "$env:USERPROFILE\.claude\skills\video-editing" -Force
Copy-Item src\SKILL.md "$env:USERPROFILE\.claude\skills\video-editing\SKILL.md" -Force

New-Item -ItemType Directory -Path "$env:USERPROFILE\.codex\skills\video-editing" -Force
Copy-Item src\SKILL.md "$env:USERPROFILE\.codex\skills\video-editing\SKILL.md" -Force
```

After installing the skill, start a fresh agent/chat session so the skill registry can reload.

## DaVinci Resolve Handoff

Use `videoedit export-edl` to generate DaVinci-friendly artifacts:

```bash
videoedit export-edl analysis/selections/*.json --output edl/
videoedit export-edl approved.json --output edl/
```

Generated handoff files include EDL, XML, M3U, and FFmpeg extraction scripts. Use DaVinci Resolve for color, sound mix, fine timing, and final delivery.

## Optional Cloud/API Tools

Cloud integrations are not required for local scanning or rough cuts. Install only when using those scripts:

```bash
python -m pip install -e "./src/python[cloud]"
```

Create a local `.env` outside version control:

```bash
ELEVENLABS_API_KEY=your_key_here
HEYGEN_API_KEY=your_key_here
DESCRIPT_API_KEY=your_key_here
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `videoedit: command not found` | Activate `.venv`, then reinstall with `python -m pip install -e ./src/python` |
| `yolo: command not found` | Activate `.venv`, then install `python -m pip install -e "./src/python[advanced]"` |
| `ffmpeg` or `ffprobe` missing | Install FFmpeg and confirm both commands are on `PATH` |
| `cv2` missing in `videoedit doctor` | Install the advanced extra in the active `.venv` |
| YOLO writes files into the repo | Use `project=/tmp/...` for smoke tests; `runs/` is ignored |
| Whisper model download is slow | Use a smaller model first, such as `tiny` or `base` |
| Windows script activation fails | Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |

## Licensing Note

This repository is MIT licensed. Ultralytics is a separate dependency distributed under AGPL-3.0 with commercial licensing options from Ultralytics. Review the Ultralytics license before using YOLO in commercial or closed-source workflows.

# Video Editing Skill - Setup Guide

Cross-platform setup for the video-editing skill. Works on Windows, macOS, and Linux.

---

## Prerequisites Checklist

| Tool | Windows | macOS | Linux | Purpose |
|------|---------|-------|-------|---------|
| **FFmpeg** | Required | Required | Required | Video processing |
| **Python 3.9+** | Required | Required | Required | Scripting |
| **Whisper** | Optional | Optional | Optional | Transcription |
| **DaVinci Resolve** | Optional | Optional | Optional | Final editing |
| **Cloud APIs** | Optional | Optional | Optional | AI tools |

---

## 1. FFmpeg Installation

### Windows

```powershell
# Using winget (recommended)
winget install ffmpeg

# Or download full build for subtitle support
# https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z
# Extract and add to PATH

# Verify installation
ffmpeg -version
ffprobe -version
```

**Add to PATH (if not automatic):**
1. Search "Environment Variables" in Windows
2. Click "Environment Variables"
3. Edit `Path` under User variables
4. Add FFmpeg bin directory (e.g., `C:\Tools\ffmpeg\bin`)

### macOS

```bash
brew install ffmpeg

# Verify
ffmpeg -version
```

### Linux

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# Or download static build
wget https://johnvansickle.com/ffmpeg/builds/ffmpeg-git-amd64-static.tar.xz
tar xvf ffmpeg-git-amd64-static.tar.xz
sudo mv ffmpeg-git-*-static/ff* /usr/local/bin/

# Verify
ffmpeg -version
```

---

## 2. Python Setup

```powershell
# Windows - Using winget
winget install Python.Python.3.12

# Verify
python --version
```

```bash
# macOS/Linux using pyenv (recommended)
brew install pyenv
pyenv install 3.12
pyenv global 3.12

# Or system Python
python3 --version
```

### Required Python Packages

```bash
# Core video processing
pip install openai-whisper

# Cloud API tools (if using)
pip install elevenlabs python-dotenv requests

# For DaVinci scripting (macOS only - comes with DaVinci)
# No pip install needed
```

---

## 3. PowerShell Module Setup

### Install the VideoEditing Module

Create the module directory:

```powershell
# Create module directory in your Documents
$modulePath = "$HOME\Documents\PowerShell\Modules\VideoEditing"
New-Item -ItemType Directory -Path $modulePath -Force

# Copy VideoEditing.psm1 to this location
# (See VideoEditing.psm1 below for full module content)
```

### Enable PowerShell Scripts (Windows)

```powershell
# Allow running scripts (current user)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify
Get-ExecutionPolicy -List
```

### Auto-load Module

Add to your PowerShell profile (`$PROFILE`):

```powershell
# Edit profile
notepad $PROFILE

# Add this line:
Import-Module VideoEditing -ErrorAction SilentlyContinue
```

---

## 4. NAS / Network Storage Setup

If storing projects on a NAS:

### Windows Network Drive Mapping

```powershell
# Map NAS drive letter
net use Z: \\nas-server\video-projects /persistent:yes

# Or with credentials
net use Z: \\nas-server\video-projects /user:yourusername password /persistent:yes
```

### Direct UNC Path (Recommended)

No mapping needed - use UNC paths directly:
```
\\nas-server\video-projects\2026\04 - April\
```

### macOS/Linux NAS Mount

```bash
# Create mount point
sudo mkdir /mnt/nas-video

# Mount (add to /etc/fstab for auto-mount)
sudo mount -t cifs //nas-server/video-projects /mnt/nas-video -o user=username,uid=1000,gid=1000

# Or use AutoFS for automatic mounting
```

---

## 5. Cloud API Configuration

Create a `.env` file for API keys:

```bash
# Location: In your project root or user directory
# Windows: C:\Users\YourName\.env
# macOS/Linux: ~/.env
```

**Environment file template:**

```bash
# Eleven Labs - AI Text-to-Speech
# Get your API key from: https://elevenlabs.io/app/settings/api-keys
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

# HeyGen - AI Avatar Video Generation
# Get your API key from: https://dashboard.heygen.com/settings
HEYGEN_API_KEY=your_heygen_api_key_here

# Descript - Text-based Video Editing
# Get your API key from: https://docs.descriptapi.com
DESCRIPT_API_KEY=your_descript_api_key_here

# Optional: Default configuration
DEFAULT_VOICE=george
DEFAULT_AVATAR=anna
```

**Load environment variables in PowerShell:**

```powershell
# Add to profile
notepad $PROFILE

# Add this function:
function Load-EnvFile {
    param($Path = "$HOME\.env")
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
    }
}

# Run on profile load
Load-EnvFile
```

---

## 6. DaVinci Resolve Setup

### Windows DaVinci Scripting

```powershell
# DaVinci Resolve Python path (usually)
# C:\Program Files\Blackmagic Design\DaVinci Resolve\python.exe

# Add to PATH if needed
$env:Path += ";C:\Program Files\Blackmagic Design\DaVinci Resolve"
```

### DaVinci Resolve Preferences

1. Open DaVinci Resolve
2. Go to **Preferences** → **General**
3. Enable **Python scripting**
4. Set **Python module path** if needed

### DaVinci Project Locations

Set default project location to your NAS:
1. **Preferences** → **Locations**
2. Set **Project Files** to your NAS path
3. Set **Cache Files** to local SSD (for performance)

---

## 7. Whisper (Transcription) Setup

### Install Whisper

```bash
pip install openai-whisper
```

### Download Models (First Run)

Whisper downloads models on first use. Pre-download:

```bash
# Download medium model (good balance)
whisper --download-medium-model

# Available models: tiny, base, small, medium, large
```

### PowerShell Function for Whisper

```powershell
function Invoke-Whisper {
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,
        
        [ValidateSet('tiny', 'base', 'small', 'medium', 'large')]
        [string]$Model = 'medium',
        
        [string]$OutputDir = "."
    )
    
    whisper $InputFile --model $Model --output_format srt --output_dir $OutputDir
}
```

---

## 8. Project Structure Template

Create a standard project structure on your NAS:

```
\\NAS\video-projects\
├── 2026\
│   ├── 01 - January\
│   ├── 02 - February\
│   └── 03 - March\
├── templates\
│   ├── lower-thirds\
│   ├── intros\
│   └── exports\
├── _assets\
│   ├── music\
│   ├── sfx\
│   └── graphics\
└── _scripts\
    └── tools\
```

### Quick Project Creator (PowerShell)

```powershell
function New-VideoProject {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Name,
        
        [string]$BasePath = "\\NAS\video-projects",
        
        [switch]$Reel,
        [switch]$YouTube
    )
    
    $date = Get-Date -Format "yyyy-MM"
    $projectPath = Join-Path $BasePath "$date - $Name"
    
    $folders = @('raw', 'audio', 'exports', 'assets', 'scripts', 'drafts')
    foreach ($folder in $folders) {
        New-Item -ItemType Directory -Path (Join-Path $projectPath $folder) -Force | Out-Null
    }
    
    if ($Reel) {
        # Reel-specific setup
    }
    if ($YouTube) {
        # YouTube-specific setup
    }
    
    Write-Host "Project created: $projectPath"
    explorer $projectPath
}
```

---

## 9. Verification

Test your setup:

```powershell
# Test FFmpeg
ffmpeg -version

# Test Python
python --version

# Test Whisper
whisper --help

# Test PowerShell module
Get-Command -Module VideoEditing

# Test NAS access
Test-Path "\\NAS\video-projects"

# Test DaVinci (if installed)
Test-Path "C:\Program Files\Blackmagic Design\DaVinci Resolve\DaVinci Resolve.exe"
```

---

## 10. Quick Reference

### Common Paths

| Platform | Config Location |
|----------|-----------------|
| Windows | `$HOME\Documents\PowerShell\` |
| macOS | `~/.config/` |
| Linux | `~/.config/` |

### Profile Files

| Platform | Profile Path |
|----------|--------------|
| Windows PowerShell | `$PROFILE` |
| Windows PowerShell 7+ | `$PROFILE` (usually `Documents\PowerShell\Microsoft.PowerShell_profile.ps1`) |
| macOS/Linux | `~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish` |

### Environment Loading

| Platform | Method |
|----------|--------|
| Windows PowerShell | `Load-EnvFile` function in profile |
| macOS/Linux | `source ~/.env` or use `direnv` |

---

## 11. Troubleshooting

### FFmpeg not found

**Windows:** Add to PATH and restart terminal
**macOS/Linux:** Ensure installation directory is in `$PATH`

### PowerShell scripts disabled

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### NAS connection issues

```powershell
# Test connection
Test-NetConnection -ComputerName nas-server -Port 445

# Re-map drive
net use Z: /delete /yes
net use Z: \\nas-server\video-projects /persistent:yes
```

### Whisper model download fails

```bash
# Manually download from GitHub
wget https://huggingface.co/openai/whisper-medium/resolve/main/medium.pt
# Move to: ~/.cache/whisper/ or C:\Users\YourName\.cache\whisper\
```

---

## 12. Next Steps

1. ✅ Install FFmpeg
2. ✅ Install Python and Whisper
3. ✅ Set up PowerShell module
4. ✅ Configure NAS access
5. ✅ Set up API keys (if using cloud tools)
6. ✅ Create first project with `New-VideoProject`
7. ✅ Test with sample footage

---

## Appendix: Full PowerShell Module

See `VideoEditing.psm1` for complete PowerShell module with all cmdlets.

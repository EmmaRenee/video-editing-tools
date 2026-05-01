# Video Editing - Quick Reference

PowerShell cmdlets for video editing workflows.

---

## Installation

```powershell
# Create module directory
$modulePath = "$HOME\Documents\PowerShell\Modules\VideoEditing"
New-Item -ItemType Directory -Path $modulePath -Force

# Copy VideoEditing.psm1 to this location

# Add to profile (auto-load on start)
Add-Content -Path $PROFILE -Value "Import-Module VideoEditing -ErrorAction SilentlyContinue"
```

---

## Cmdlet Index

### Video Information

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `Get-VideoInfo` | Get video metadata | `Get-VideoInfo race.mp4` |
| `Find-Silence` | Detect quiet sections | `Find-Silence video.mp4` |
| `Find-SceneChanges` | Detect cut points | `Find-SceneChanges video.mp4` |

### Format Conversion

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `ConvertTo-Reel` | 9:16 vertical | `ConvertTo-Reel clip.mp4` |
| `ConvertTo-YouTube` | 16:9 1080p | `ConvertTo-YouTube clip.mp4` |
| `ConvertTo-Square` | 1:1 1080x1080 | `ConvertTo-Square clip.mp4` |

### Cutting & Joining

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `Copy-VideoSegment` | Extract clip | `Copy-VideoSegment in.mp4 out.mp4 -Start "00:01:00" -End "00:02:00"` |
| `Join-VideoFiles` | Concatenate | `Join-VideoFiles clip1.mp4,clip2.mp4 output.mp4` |

### Audio

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `Remove-Silence` | Cut dead air | `Remove-Silence in.mp4 out.mp4` |
| `Set-AudioNormalize` | Fix levels | `Set-AudioNormalize in.mp4 out.mp4` |
| `Export-Audio` | Extract audio | `Export-Audio video.mp4 audio.wav` |

### Quality & Proxy

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `New-VideoProxy` | Create proxy | `New-VideoProxy raw.mp4 proxy.mp4` |
| `Export-ForDaVinci` | Export for edit | `Export-ForDaVinci cut.mp4 for_davinci.mov` |

### Captions

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `Add-Captions` | Burn subtitles | `Add-Captions vid.mp4 subs.srt out.mp4` |
| `Invoke-WhisperTranscribe` | Transcribe | `Invoke-WhisperTranscribe vid.mp4` |

### Projects

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `New-VideoProject` | New project | `New-VideoProject "Race Day" -Type Reel` |

### Batch

| Cmdlet | Purpose | Example |
|--------|---------|---------|
| `Start-BatchConvert` | Bulk convert | `Start-BatchConvert -InputFolder raw -OutputFolder done` |

---

## Common Workflows

### Create Instagram Reel

```powershell
# Import module (or auto-load from profile)
Import-Module VideoEditing

# Convert to reel format
ConvertTo-Reel raw_footage.mp4 reel_output.mp4

# Add captions
Invoke-WhisperTranscribe reel_output.mp4 -Model small
Add-Captions reel_output.mp4 reel_output.srt reel_final.mp4 -FontSize 28
```

### Extract Multiple Highlights

```powershell
# Extract segments (from timestamps)
Copy-VideoSegment race.mp4 overtake.mp4 -Start "00:12:30" -End "00:13:30"
Copy-VideoSegment race.mp4 incident.mp4 -Start "00:45:00" -End "00:46:30"
Copy-VideoSegment race.mp4 podium.mp4 -Start "01:22:30" -End "01:24:00"

# Convert all to reels
Get-ChildItem *.mp4 | ConvertTo-Reel -OutputFolder reels
```

### Join Clips

```powershell
# Method 1: Array of files
Join-VideoFiles clip1.mp4,clip2.mp4,clip3.mp4 combined.mp4

# Method 2: From pipeline
Get-ChildInfo clips/*.mp4 | Sort-Object Name | Join-VideoFiles output.mp4
```

### Create Project and Process Footage

```powershell
# Create project structure
New-VideoProject "Transmission Build" -Type YouTube -BasePath \\NAS\projects

# Process raw footage
Start-BatchConvert -InputFolder .\raw -OutputFolder .\drafts -Filter "scale=960:-2"
```

### Prepare for DaVinci

```powershell
# Create EDL-worthy clips from Claude-identified timestamps
Copy-VideoSegment race.mp4 highlight1.mp4 -Start 123.5 -End 145.2
Copy-VideoSegment race.mp4 highlight2.mp4 -Start 312.0 -End 335.8

# Export in DaVinci-friendly format
Export-ForDaVinci highlight1.mp4 for_davinci1.mov -Codec ProRes
Export-ForDaVinci highlight2.mp4 for_davinci2.mov -Codec ProRes
```

### Fix Audio Issues

```powershell
# Remove silence/dead air
Remove-Silence interview.mp4 interview_clean.mp4

# Normalize audio levels
Set-AudioNormalize interview_clean.mp4 interview_final.mp4
```

---

## Parameter Aliases

Most cmdlets accept input via pipeline:

```powershell
# All equivalent
ConvertTo-Reel video.mp4
Get-VideoInfo video.mp4 | ConvertTo-Reel
"video.mp4" | ConvertTo-Reel
Get-ChildItem *.mp4 | ConvertTo-Reel
```

---

## Tips & Tricks

### Quick duration check
```powershell
Get-VideoInfo *.mp4 | Select-Object Name, Duration
```

### Batch convert with custom filter
```powershell
Start-BatchConvert -InputFolder raw -OutputFolder done -Filter "crop=ih*9/16:ih,scale=1080:1920"
```

### Create proxy for faster editing
```powershell
Get-ChildItem 4k_footage/*.mp4 | ForEach-Object {
    New-VideoProxy $_.FullName "proxies\$($_.BaseName)_proxy.mp4" -Width 960
}
```

### Detect all cut points
```powershell
$scenes = Find-SceneChanges long_video.mp4
$scenes | Format-Table Index, Formatted
```

---

## Error Handling

```powershell
# Test if FFmpeg is available
Get-Command ffmpeg -ErrorAction SilentlyContinue

# Test module is loaded
Get-Command -Module VideoEditing

# Verbose output for debugging
ConvertTo-Reel video.mp4 -Verbose
```

---

## FFmpeg-Free Commands

These cmdlets work without FFmpeg (for reference):

```powershell
# Get video info (Windows built-in)
Get-Item video.mp4 | Select-Object Name, Length, LastWriteTime

# Get media info (requires shell)
shell:media // can be used in Explorer
```

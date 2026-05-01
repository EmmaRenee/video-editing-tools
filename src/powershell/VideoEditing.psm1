# VideoEditing.psm1
# PowerShell module for video editing workflows
# Cross-platform compatible (Windows-focused, macOS/Linux friendly)

# Requires FFmpeg to be installed and in PATH
# Requires Whisper for transcription (optional)

---

# Private Helper Functions

function Test-Ffmpeg {
    <#
    .SYNOPSIS
        Verify FFmpeg is available
    #>
    $null = Get-Command ffmpeg -ErrorAction SilentlyContinue
    return $?
}

function Test-Whisper {
    <#
    .SYNOPSIS
        Verify Whisper is available
    #>
    $null = Get-Command whisper -ErrorAction SilentlyContinue
    return $?
}

function Get-VideoDuration {
    <#
    .SYNOPSIS
        Get video duration using ffprobe
    #>
    param([string]$Path)

    $output = ffprobe -i $Path -show_entries format=duration -v quiet -of csv="p=0" 2>&1
    if ($output -match '^\d+\.?\d*$') {
        return [double]$output
    }
    return $null
}

function Format-TimeSpan {
    <#
    .SYNOPSIS
        Convert seconds to FFmpeg time format (HH:MM:SS)
    #>
    param([double]$Seconds)

    $ts = [TimeSpan]::FromSeconds($Seconds)
    return "{0:00}:{1:00}:{2:00}" -f $ts.Hours, $ts.Minutes, $ts.Seconds
}

---

# Core Video Cmdlets

function Get-VideoInfo {
    <#
    .SYNOPSIS
        Get detailed information about a video file
    .EXAMPLE
        Get-VideoInfo race_footage.mp4
    .EXAMPLE
        Get-VideoInfo *.mp4 | Select-Object Name, Duration, Resolution, Codec
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true, ValueFromPipelineByPropertyName=$true)]
        [Alias('FullName', 'Path')]
        [string[]]$InputFile
    )

    begin {
        if (-not (Test-Ffmpeg)) {
            Write-Error "FFmpeg not found. Please install FFmpeg and add to PATH."
            return
        }
    }

    process {
        foreach ($file in $InputFile) {
            if (-not (Test-Path $file)) {
                Write-Warning "File not found: $file"
                continue
            }

            $resolvedPath = (Resolve-Path $file).Path

            # Run ffprobe and parse JSON output
            $json = ffprobe -i $resolvedPath -show_format -show_streams -v quiet -of json 2>&1 | ConvertFrom-Json

            $videoStream = $json.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1
            $audioStream = $json.streams | Where-Object { $_.codec_type -eq 'audio' } | Select-Object -First 1

            [PSCustomObject]@{
                Name          = Split-Path $file -Leaf
                Path          = $resolvedPath
                Duration      = if ($json.format.duration) { [TimeSpan]::FromSeconds($json.format.duration) } else { $null }
                Resolution    = if ($videoStream) { "$($videoStream.width)x$($videoStream.height)" } else { $null }
                Width         = $videoStream.width
                Height        = $videoStream.height
                VideoCodec    = $videoStream.codec_name
                AudioCodec    = $audioStream.codec_name
                FrameRate     = if ($videoStream.r_frame_rate) { [double]$videoStream.r_frame_rate.Split('/')[0] / [double]$videoStream.r_frame_rate.Split('/')[1] } else { $null }
                Bitrate       = if ($json.format.bit_rate) { [int]$json.format.bit_rate / 1000 } else { $null }
                Size          = if ($json.format.size) { [int]$json.format.size / 1MB } else { $null }
            }
        }
    }
}

function Remove-Silence {
    <#
    .SYNOPSIS
        Remove silent or quiet sections from video
    .EXAMPLE
        Remove-Silence input.mp4 output.mp4 -Threshold -35dB
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        # Threshold in dB (default: -35dB)
        [double]$Threshold = -35,

        # Minimum silence duration in seconds
        [double]$MinSilence = 0.5
    )

    if (-not (Test-Ffmpeg)) { return }

    $filter = "silenceremove=start_periods=1:start_silence=$MinSilence:start_threshold=${Threshold}dB:stop_periods=-1:stop_silence=0:stop_threshold=${Threshold}dB"

    ffmpeg -i $InputFile -af $filter -c:v copy $OutputFile -y

    if ($?) {
        Write-Host "Removed silence from $InputFile -> $OutputFile"
    }
}

function Set-AudioNormalize {
    <#
    .SYNOPSIS
        Normalize audio to EBU R128 loudness standard
    .EXAMPLE
        Set-AudioNormalize input.mp4 output.mp4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        # Target integrated loudness in LUFS (default: -16)
        [double]$TargetI = -16,

        # True peak in dBTP (default: -1.5)
        [double]$TargetTP = -1.5,

        # Loudness range (default: 11)
        [double]$LRA = 11
    )

    if (-not (Test-Ffmpeg)) { return }

    $filter = "loudnorm=I=$TargetI:TP=$TargetTP:LRA=$LRA"

    ffmpeg -i $InputFile -af $filter -c:v copy $OutputFile -y

    if ($?) {
        Write-Host "Normalized audio: $InputFile -> $OutputFile"
    }
}

function Find-Silence {
    <#
    .SYNOPSIS
        Detect silent sections in video
    .EXAMPLE
        Find-Silence race_footage.mp4 -Threshold -30dB
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        # Noise threshold in dB (default: -30dB)
        [double]$Threshold = -30,

        # Minimum silence duration in seconds
        [double]$MinDuration = 1.0
    )

    if (-not (Test-Ffmpeg)) { return }

    $filter = "silencedetect=noise=${Threshold}dB:d=$MinDuration"
    $output = ffmpeg -i $InputFile -af $filter -f null - 2>&1

    # Parse silence detection output
    $results = $output | Select-String "silence_\w+:\s+(\d+\.?\d*)" | ForEach-Object {
        if ($_ -match "silence_start:\s+(\d+\.?\d*)") {
            [PSCustomObject]@{
                Type = 'SilenceStart'
                Time = [double]$matches[1]
                Formatted = Format-TimeSpan $matches[1]
            }
        }
        elseif ($_ -match "silence_end:\s+(\d+\.?\d*)") {
            [PSCustomObject]@{
                Type = 'SilenceEnd'
                Time = [double]$matches[1]
                Formatted = Format-TimeSpan $matches[1]
            }
        }
    }

    return $results
}

---

# Format Conversion Cmdlets

function ConvertTo-Reel {
    <#
    .SYNOPSIS
        Convert video to Instagram Reel format (9:16 vertical, 1080x1920)
    .EXAMPLE
        ConvertTo-Reel clip.mp4 reel_output.mp4
    .EXAMPLE
        Get-ChildItem *.mp4 | ConvertTo-Reel
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true, ValueFromPipelineByPropertyName=$true)]
        [Alias('FullName', 'Path')]
        [string[]]$InputFile,

        [Parameter(Mandatory=$false)]
        [string]$OutputFolder = ".",

        # Output suffix (default: _reel)
        [string]$Suffix = "_reel"
    )

    begin {
        if (-not (Test-Ffmpeg)) { return }
    }

    process {
        foreach ($file in $InputFile) {
            if (-not (Test-Path $file)) {
                Write-Warning "File not found: $file"
                continue
            }

            $inputPath = (Resolve-Path $file).Path
            $basename = [System.IO.Path]::GetFileNameWithoutExtension($file)
            $ext = [System.IO.Path]::GetExtension($file)
            $outputPath = Join-Path $OutputFolder "${basename}${Suffix}${ext}"

            # Center crop to 9:16 and scale to 1080x1920
            ffmpeg -i $inputPath -vf "crop=ih*9/16:ih:(iw-iw*9/16/ih)/2:0,scale=1080:1920" -c:a copy $outputPath -y

            if ($?) {
                Write-Host "Created reel: $outputPath"
            }
        }
    }
}

function ConvertTo-YouTube {
    <#
    .SYNOPSIS
        Convert video to YouTube format (16:9 horizontal, 1920x1080)
    .EXAMPLE
        ConvertTo-YouTube clip.mp4 youtube_output.mp4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true, ValueFromPipelineByPropertyName=$true)]
        [Alias('FullName', 'Path')]
        [string[]]$InputFile,

        [Parameter(Mandatory=$false)]
        [string]$OutputFolder = ".",

        [string]$Suffix = "_youtube"
    )

    begin {
        if (-not (Test-Ffmpeg)) { return }
    }

    process {
        foreach ($file in $InputFile) {
            if (-not (Test-Path $file)) {
                Write-Warning "File not found: $file"
                continue
            }

            $inputPath = (Resolve-Path $file).Path
            $basename = [System.IO.Path]::GetFileNameWithoutExtension($file)
            $ext = [System.IO.Path]::GetExtension($file)
            $outputPath = Join-Path $OutputFolder "${basename}${Suffix}${ext}"

            # Scale to 1080p height, maintain aspect ratio
            ffmpeg -i $inputPath -vf "scale=-2:1080" -c:a copy $outputPath -y

            if ($?) {
                Write-Host "Created YouTube video: $outputPath"
            }
        }
    }
}

function ConvertTo-Square {
    <#
    .SYNOPSIS
        Convert video to square format (1:1, 1080x1080)
    .EXAMPLE
        ConvertTo-Square clip.mp4 square_output.mp4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true, ValueFromPipelineByPropertyName=$true)]
        [Alias('FullName', 'Path')]
        [string[]]$InputFile,

        [Parameter(Mandatory=$false)]
        [string]$OutputFolder = ".",

        [string]$Suffix = "_square"
    )

    begin {
        if (-not (Test-Ffmpeg)) { return }
    }

    process {
        foreach ($file in $InputFile) {
            if (-not (Test-Path $file)) {
                Write-Warning "File not found: $file"
                continue
            }

            $inputPath = (Resolve-Path $file).Path
            $basename = [System.IO.Path]::GetFileNameWithoutExtension($file)
            $ext = [System.IO.Path]::GetExtension($file)
            $outputPath = Join-Path $OutputFolder "${basename}${Suffix}${ext}"

            # Center crop to 1:1 and scale to 1080x1080
            ffmpeg -i $inputPath -vf "crop=ih:ih:(iw-ih)/2:0,scale=1080:1080" -c:a copy $outputPath -y

            if ($?) {
                Write-Host "Created square video: $outputPath"
            }
        }
    }
}

---

# Cutting and Editing Cmdlets

function Copy-VideoSegment {
    <#
    .SYNOPSIS
        Extract a segment from video without re-encoding
    .EXAMPLE
        Copy-VideoSegment input.mp4 output.mp4 -Start "00:01:00" -End "00:02:00"
    .EXAMPLE
        Copy-VideoSegment input.mp4 output.mp4 -Start 60 -End 120
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        [Parameter(Mandatory=$true)]
        # Start time (seconds or HH:MM:SS format)
        [object]$Start,

        [Parameter(Mandatory=$true)]
        # End time (seconds or HH:MM:SS format)
        [object]$End
    )

    if (-not (Test-Ffmpeg)) { return }

    $startTime = if ($Start -is [string]) { $Start } else { Format-TimeSpan $Start }
    $endTime = if ($End -is [string]) { $End } else { Format-TimeSpan $End }

    ffmpeg -i $InputFile -ss $startTime -to $endTime -c copy $OutputFile -y

    if ($?) {
        Write-Host "Extracted segment: $OutputFile"
    }
}

function Join-VideoFiles {
    <#
    .SYNOPSIS
        Concatenate multiple video files
    .EXAMPLE
        Join-VideoFiles clip1.mp4,clip2.mp4,clip3.mp4 output.mp4
    .EXAMPLE
        Get-ChildItem clips/*.mp4 | Sort-Object Name | Join-VideoFiles combined.mp4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true)]
        [string[]]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile
    )

    begin {
        if (-not (Test-Ffmpeg)) { return }

        $files = @()
        $tempDir = Join-Path $env:TEMP "VideoJoin_$(Get-Random)"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    }

    process {
        foreach ($file in $InputFile) {
            if (Test-Path $file) {
                $files += (Resolve-Path $file).Path
            }
        }
    }

    end {
        if ($files.Count -eq 0) {
            Write-Warning "No valid input files"
            Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            return
        }

        # Create concat file
        $concatFile = Join-Path $tempDir "concat.txt"
        foreach ($file in $files) {
            # Escape path for FFmpeg concat
            $escapedPath = $file -replace '\\', '/'
            "file '$escapedPath'" | Add-Content -Path $concatFile
        }

        # Join files
        ffmpeg -f concat -safe 0 -i $concatFile -c copy $OutputFile -y

        if ($?) {
            Write-Host "Joined $($files.Count) files into: $OutputFile"
        }

        # Cleanup
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

---

# Proxy and Quality Cmdlets

function New-VideoProxy {
    <#
    .SYNOPSIS
        Create a lower-quality proxy file for faster editing
    .EXAMPLE
        New-VideoProxy raw_4k.mp4 proxy.mp4
    .EXAMPLE
        New-VideoProxy raw_4k.mp4 proxy.mp4 -Width 960 -CRF 28
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        # Proxy width (default: 960, height calculated)
        [int]$Width = 960,

        # Quality (lower = better, 18-28 typical)
        [int]$CRF = 28,

        # Encoding preset (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)
        [string]$Preset = "ultrafast"
    )

    if (-not (Test-Ffmpeg)) { return }

    ffmpeg -i $InputFile -vf "scale=$Width:-2" -c:v libx264 -preset $Preset -crf $CRF -c:a copy $OutputFile -y

    if ($?) {
        Write-Host "Created proxy: $OutputFile"
    }
}

function Export-ForDaVinci {
    <#
    .SYNOPSIS
        Export video in DaVinci Resolve-friendly format
    .EXAMPLE
        Export-ForDaVinci cut.mp4 for_davinci.mov -Codec ProRes
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        [ValidateSet('ProRes', 'DNxHD', 'DNxHR')]
        [string]$Codec = 'ProRes'
    )

    if (-not (Test-Ffmpeg)) { return }

    switch ($Codec) {
        'ProRes' {
            ffmpeg -i $InputFile -c:v prores_ks -profile:v 3 -c:a pcm_s16le $OutputFile -y
        }
        'DNxHD' {
            ffmpeg -i $InputFile -c:v dnxhd -profile:v dqxhr_444 -pix_fmt rgb48le -c:a pcm_s16le $OutputFile -y
        }
        'DNxHR' {
            ffmpeg -i $InputFile -c:v dnxhd -profile:v dqxhr_444 -pix_fmt rgb48le -c:a pcm_s16le $OutputFile -y
        }
    }

    if ($?) {
        Write-Host "Exported for DaVinci ($Codec): $OutputFile"
    }
}

---

# Caption and Subtitle Cmdlets

function Add-Captions {
    <#
    .SYNOPSIS
        Burn subtitles into video
    .EXAMPLE
        Add-Captions video.mp4 captions.srt output.mp4
    .EXAMPLE
        Add-Captions video.mp4 captions.srt output.mp4 -FontSize 28 -BorderColor white
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$SubtitleFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        [int]$FontSize = 24,

        [ValidateSet('black', 'white', 'none')]
        [string]$BorderColor = 'black',

        [ValidateSet('white', 'yellow', 'cyan', 'green', 'magenta')]
        [string]$FontColor = 'white',

        # Use FontName parameter instead of FontName to avoid conflict
        [string]$FontName = 'Arial'
    )

    if (-not (Test-Ffmpeg)) { return }

    if (-not (Test-Path $SubtitleFile)) {
        Write-Error "Subtitle file not found: $SubtitleFile"
        return
    }

    # Build force_style string
    $borderStyle = if ($BorderColor -eq 'none') { 0 } elseif ($BorderColor -eq 'white') { 1 } else { 1 }
    $borderStyleValue = if ($BorderColor -eq 'white') { 1 } else { 1 }

    $forceStyle = "FontSize=$FontSize,BorderStyle=$borderStyleValue,FontName=$FontName"

    # Note: On Windows, subtitle paths may need special handling
    $subtitlePath = $SubtitleFile -replace '\\', '/'

    ffmpeg -i $InputFile -vf "subtitles='$subtitlePath':force_style='$forceStyle'" $OutputFile -y

    if ($?) {
        Write-Host "Added captions: $OutputFile"
    }
}

function Invoke-WhisperTranscribe {
    <#
    .SYNOPSIS
        Transcribe video audio using OpenAI Whisper
    .EXAMPLE
        Invoke-WhisperTranscribe video.mp4 -Model medium
    .EXAMPLE
        Invoke-WhisperTranscribe video.mp4 -Model small -OutputDir transcripts/
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true, ValueFromPipeline=$true)]
        [string]$InputFile,

        [ValidateSet('tiny', 'base', 'small', 'medium', 'large')]
        [string]$Model = 'medium',

        [string]$OutputDir = ".",

        [switch]$VerboseOutput
    )

    begin {
        if (-not (Test-Whisper)) {
            Write-Error "Whisper not found. Install with: pip install openai-whisper"
            return
        }
    }

    process {
        if (-not (Test-Path $InputFile)) {
            Write-Warning "File not found: $InputFile"
            return
        }

        $inputPath = (Resolve-Path $InputFile).Path

        # Build whisper command
        $args = @($inputPath, "--model", $Model, "--output_format", "srt", "--output_dir", $OutputDir)
        if ($VerboseOutput) { $args += "--verbose" }

        & whisper @args

        $basename = [System.IO.Path]::GetFileNameWithoutExtension($InputFile)
        $srtFile = Join-Path $OutputDir "$basename.srt"

        if (Test-Path $srtFile) {
            Write-Host "Transcription saved: $srtFile"
        }
    }
}

---

# Scene Detection Cmdlets

function Find-SceneChanges {
    <#
    .SYNOPSIS
        Detect scene changes in video (useful for finding cut points)
    .EXAMPLE
        Find-SceneChanges video.mp4 -Threshold 0.4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        # Scene threshold (0.0-1.0, default 0.4)
        [double]$Threshold = 0.4
    )

    if (-not (Test-Ffmpeg)) { return }

    $output = ffmpeg -i $InputFile -vf "select='gt(scene,$Threshold)',showinfo" -vsync vfr -f null - 2>&1

    # Parse pts_time values
    $timestamps = $output | Select-String "pts_time:(\d+\.?\d*)" | ForEach-Object {
        if ($_ -match "pts_time:(\d+\.?\d*)") {
            [double]$matches[1]
        }
    }

    $results = @()
    for ($i = 0; $i -lt $timestamps.Count; $i++) {
        $results += [PSCustomObject]@{
            Index = $i + 1
            Time = $timestamps[$i]
            Formatted = Format-TimeSpan $timestamps[$i]
        }
    }

    return $results
}

---

# Project Management Cmdlets

function New-VideoProject {
    <#
    .SYNOPSIS
        Create a new video project with standard folder structure
    .EXAMPLE
        New-VideoProject "Transmission Rebuild" -Type YouTube
    .EXAMPLE
        New-VideoProject "Day at Track" -Type Reel -BasePath \\NAS\projects
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Name,

        [ValidateSet('Reel', 'YouTube', 'Documentary', 'Interview', 'BRoll')]
        [string]$Type = 'Reel',

        [string]$BasePath = "."
    )

    $date = Get-Date -Format "yyyy-MM"
    $projectName = "$date - $Name"
    $projectPath = Join-Path $BasePath $projectName

    # Create standard folders
    $folders = @('raw', 'audio', 'exports', 'assets', 'scripts', 'drafts')
    foreach ($folder in $folders) {
        $folderPath = Join-Path $projectPath $folder
        New-Item -ItemType Directory -Path $folderPath -Force | Out-Null
    }

    # Create README
    $readmePath = Join-Path $projectPath "README.md"
    @"
# $Name

**Created:** $(Get-Date -Format "yyyy-MM-dd")
**Type:** $Type

## Project Structure

- **raw/** - Raw footage
- **audio/** - Music, SFX
- **exports/** - Final exports
- **assets/** - Graphics, lower thirds
- **scripts/** - Scripts, transcripts
- **drafts/** - Work in progress edits

## Workflow

1. Copy raw footage to \`raw/\`
2. Extract highlights with FFmpeg
3. Create rough cut
4. Format for target platform
5. Add captions (optional)
6. Export final version

"@ | Out-File -FilePath $readmePath -Encoding UTF8

    Write-Host "Project created: $projectPath"

    # Open in Explorer
    explorer $projectPath

    return [PSCustomObject]@{
        Name = $projectName
        Path = $projectPath
        Type = $Type
    }
}

---

# Audio Extraction Cmdlets

function Export-Audio {
    <#
    .SYNOPSIS
        Extract audio from video file
    .EXAMPLE
        Export-Audio video.mp4 audio.wav
    .EXAMPLE
        Export-Audio video.mp4 audio.mp3 -Bitrate 192k
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$InputFile,

        [Parameter(Mandatory=$true)]
        [string]$OutputFile,

        [string]$Codec = 'pcm_s16le',

        [string]$Bitrate = '128k',

        [int]$SampleRate = 16000
    )

    if (-not (Test-Ffmpeg)) { return }

    $ext = [System.IO.Path]::GetExtension($OutputFile)

    if ($ext -eq '.mp3') {
        ffmpeg -i $InputFile -vn -acodec libmp3lame -ab $Bitrate -ar $SampleRate $OutputFile -y
    }
    elseif ($ext -eq '.wav') {
        ffmpeg -i $InputFile -vn -acodec pcm_s16le -ar $SampleRate $OutputFile -y
    }
    else {
        ffmpeg -i $InputFile -vn -acodec $Codec -ar $SampleRate $OutputFile -y
    }

    if ($?) {
        Write-Host "Exported audio: $OutputFile"
    }
}

---

# Batch Processing Cmdlets

function Start-BatchConvert {
    <#
    .SYNOPSIS
        Batch convert videos with a custom FFmpeg command
    .EXAMPLE
        Start-BatchConvert -InputFolder .\raw -OutputFolder .\converted -Filter "scale=1080:1920"
    #>
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$InputFolder = ".",

        [string]$OutputFolder = ".",

        [string]$Filter,

        [string]$FileFilter = "*.mp4",

        [string]$OutputSuffix = "_converted"
    )

    if (-not (Test-Ffmpeg)) { return }

    $files = Get-ChildItem -Path $InputFolder -Filter $FileFilter -File

    if ($files.Count -eq 0) {
        Write-Warning "No files found matching: $FileFilter"
        return
    }

    New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null

    foreach ($file in $files) {
        $inputPath = $file.FullName
        $basename = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
        $ext = $file.Extension
        $outputPath = Join-Path $OutputFolder "${basename}${OutputSuffix}${ext}"

        if ($PSCmdlet.ShouldProcess($inputPath, "Convert to $outputPath")) {
            if ($Filter) {
                ffmpeg -i $inputPath -vf $Filter -c:a copy $outputPath -y
            }
            else {
                ffmpeg -i $inputPath -c:v libx264 -preset medium -crf 23 -c:a copy $outputPath -y
            }

            if ($?) {
                Write-Host "Converted: $($file.Name) -> $outputPath"
            }
        }
    }
}

---

# Export Module Members

Export-ModuleMember -Function @(
    # Info
    'Get-VideoInfo'

    # Audio
    'Remove-Silence'
    'Set-AudioNormalize'
    'Find-Silence'
    'Export-Audio'

    # Format conversion
    'ConvertTo-Reel'
    'ConvertTo-YouTube'
    'ConvertTo-Square'

    # Cutting/joining
    'Copy-VideoSegment'
    'Join-VideoFiles'

    # Quality/proxy
    'New-VideoProxy'
    'Export-ForDaVinci'

    # Captions
    'Add-Captions'
    'Invoke-WhisperTranscribe'

    # Scene detection
    'Find-SceneChanges'

    # Projects
    'New-VideoProject'

    # Batch
    'Start-BatchConvert'
)

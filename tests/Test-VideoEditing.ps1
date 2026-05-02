# Test-VideoEditing.ps1
# Test script for Video Editing Tools
# Run this after installation to verify everything works

Write-Host "=" * 60
Write-Host "Video Editing Tools - Installation Test"
Write-Host "=" * 60
Write-Host ""

$testsPassed = 0
$testsFailed = 0

function Test-Step {
    param([string]$Name, [scriptblock]$Script)

    Write-Host "Testing: $Name" -ForegroundColor Cyan
    try {
        $result = & $Script
        if ($LASTEXITCODE -eq 0 -and $?) {
            Write-Host "  ✅ PASS" -ForegroundColor Green
            $global:testsPassed++
            return $true
        }
        else {
            Write-Host "  ❌ FAIL: $result" -ForegroundColor Red
            $global:testsFailed++
            return $false
        }
    }
    catch {
        Write-Host "  ❌ ERROR: $_" -ForegroundColor Red
        $global:testsFailed++
        return $false
    }
}

# Test 1: FFmpeg Installation
Write-Host "`n=== Prerequisites ===`n"
Test-Step "FFmpeg is installed" {
    $version = ffmpeg -version 2>&1 | Select-Object -First 1
    if ($version -match "ffmpeg version") {
        return $version
    }
    throw "FFmpeg not found"
}

Test-Step "FFprobe is installed" {
    $version = ffprobe -version 2>&1 | Select-Object -First 1
    if ($version -match "ffprobe version") {
        return $version
    }
    throw "FFprobe not found"
}

# Test 2: PowerShell Module
Write-Host "`n=== PowerShell Module ===`n"
Test-Step "Module can be imported" {
    Import-Module VideoEditing -ErrorAction Stop
    return "Module loaded successfully"
}

Test-Step "Cmdlets are available" {
    $cmds = Get-Command -Module VideoEditing
    if ($cmds.Count -ge 10) {
        return "Found $($cmds.Count) cmdlets"
    }
    throw "Only found $($cmds.Count) cmdlets (expected 10+)"
}

# List available cmdlets
Write-Host "`nAvailable cmdlets:" -ForegroundColor Yellow
Get-Command -Module VideoEditing | Select-Object -ExpandProperty Name | ForEach-Object {
    Write-Host "  - $_"
}

# Test 3: Create Test Project
Write-Host "`n=== Project Creation ===`n"
$testProjectPath = Join-Path $env:TEMP "VideoEditingTest"

Test-Step "Create test project" {
    Remove-Item $testProjectPath -Recurse -Force -ErrorAction SilentlyContinue
    $project = New-VideoProject "Test Project" -Type Reel -BasePath $env:TEMP
    if (Test-Path $project.Path) {
        return "Created at: $($project.Path)"
    }
    throw "Project path not found"
}

Test-Step "Project folders exist" {
    $folders = @('raw', 'audio', 'exports', 'assets', 'scripts', 'drafts')
    $missing = @()
    foreach ($folder in $folders) {
        $path = Join-Path $testProjectPath $folder
        if (-not (Test-Path $path)) {
            $missing += $folder
        }
    }
    if ($missing.Count -eq 0) {
        return "All folders created"
    }
    throw "Missing folders: $($missing -join ', ')"
}

# Test 4: Optional Tools Check
Write-Host "`n=== Optional Tools ===`n"
Test-Step "Python availability" {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $version = python --version 2>&1
        return $version
    }
    return "Python not installed (optional)"
}

Test-Step "Whisper availability" {
    $whisper = Get-Command whisper -ErrorAction SilentlyContinue
    if ($whisper) {
        return "Whisper installed"
    }
    return "Whisper not installed (optional)"
}

# Test 5: FFmpeg Functionality (requires test video)
Write-Host "`n=== FFmpeg Functionality (requires test video) ===`n"
Write-Host "To test FFmpeg workflows, provide a test video path:" -ForegroundColor Yellow
Write-Host "  .\Test-VideoEditing.ps1 -TestVideo 'path\to\video.mp4'"
Write-Host ""

# Cleanup
Remove-Item $testProjectPath -Recurse -Force -ErrorAction SilentlyContinue

# Summary
Write-Host "`n" + "=" * 60
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "=" * 60
Write-Host "Passed: $testsPassed" -ForegroundColor Green
Write-Host "Failed: $testsFailed" -ForegroundColor $(if ($testsFailed -gt 0) { "Red" } else { "Green" })
Write-Host ""

if ($testsFailed -eq 0) {
    Write-Host "✅ All tests passed! Video Editing Tools is ready to use." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "❌ Some tests failed. Please check the errors above." -ForegroundColor Red
    exit 1
}

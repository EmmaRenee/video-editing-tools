#!/usr/bin/env python3
"""
Inventory Scanner - Scan footage directory and generate reports
"""
import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List

def get_video_info(filepath: Path) -> Dict:
    """Extract video metadata using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size:stream=width,height,codec_type,codec_name,r_frame_rate",
        "-of", "json", str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    
    data = json.loads(result.stdout)
    
    info = {
        "filename": filepath.name,
        "filepath": str(filepath),
        "size_mb": round(int(data["format"]["size"]) / (1024*1024), 2) if "size" in data["format"] else 0,
    }
    
    # Get duration
    if "duration" in data["format"]:
        info["duration"] = round(float(data["format"]["duration"]), 2)
    
    # Get video stream info
    for stream in data.get("streams", []):
        if stream["codec_type"] == "video":
            info["width"] = stream["width"]
            info["height"] = stream["height"]
            info["codec"] = stream["codec_name"]
            if "r_frame_rate" in stream:
                fps_str = stream["r_frame_rate"]
                num, den = fps_str.split("/")
                info["fps"] = round(int(num) / int(den), 2)
            break
    
    return info

def scan_directory(directory: Path, extensions: List[str] = None) -> List[Dict]:
    """Scan directory for video files."""
    if extensions is None:
        extensions = ["mp4", "mov", "mkv", "MOV", "MP4"]
    
    videos = []
    for ext in extensions:
        videos.extend(directory.rglob(f"*.{ext}"))
    
    results = []
    for video in sorted(videos):
        info = get_video_info(video)
        if info:
            results.append(info)
    
    return results

def format_duration(seconds: float) -> str:
    """Format seconds to HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def generate_csv(results: List[Dict], output: Path) -> None:
    """Generate CSV inventory report."""
    with open(output, 'w') as f:
        # Header
        f.write("filename,duration,resolution,codec,fps,size_mb,filepath\n")
        
        for item in results:
            duration = item.get("duration", 0)
            resolution = f"{item.get('width', 0)}x{item.get('height', 0)}" if "width" in item else "N/A"
            f.write(f"{item['filename']},{format_duration(duration)},{resolution},{item.get('codec', 'N/A')},{item.get('fps', 'N/A')},{item['size_mb']},\"{item['filepath']}\"\n")
    
    print(f"CSV report: {output}")

def generate_markdown(results: List[Dict], output: Path) -> None:
    """Generate markdown summary report."""
    total_duration = sum(r.get("duration", 0) for r in results)
    total_size = sum(r.get("size_mb", 0) for r in results)
    
    with open(output, 'w') as f:
        f.write(f"# Footage Inventory\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"- **Files:** {len(results)}\n")
        f.write(f"- **Total Duration:** {format_duration(total_duration)}\n")
        f.write(f"- **Total Size:** {round(total_size / 1024, 2)} GB\n\n")
        
        # Resolution breakdown
        res_counts = {}
        for r in results:
            res = f"{r.get('width', 0)}x{r.get('height', 0)}"
            res_counts[res] = res_counts.get(res, 0) + 1
        
        f.write(f"## Resolution Breakdown\n\n")
        for res, count in sorted(res_counts.items(), reverse=True):
            f.write(f"- {res}: {count} files\n")
        
        f.write(f"\n## Files\n\n")
        f.write(f"| Filename | Duration | Resolution | Codec | FPS | Size |\n")
        f.write(f"|----------|----------|------------|-------|-----|------|\n")
        
        for r in results[:100]:  # Limit to first 100
            f.write(f"| {r['filename'][:40]} | {format_duration(r.get('duration', 0))} | ")
            f.write(f"{r.get('width', 0)}x{r.get('height', 0)} | {r.get('codec', 'N/A')} | ")
            f.write(f"{r.get('fps', 'N/A')} | {r['size_mb']} MB |\n")
        
        if len(results) > 100:
            f.write(f"\n*... and {len(results) - 100} more files*\n")
    
    print(f"Markdown report: {output}")

def generate_json(results: List[Dict], output: Path) -> None:
    """Generate JSON for Claude analysis."""
    with open(output, 'w') as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "count": len(results),
            "total_duration": sum(r.get("duration", 0) for r in results),
            "videos": results
        }, f, indent=2)
    
    print(f"JSON export: {output}")

def main():
    parser = argparse.ArgumentParser(
        description="Scan footage directory and generate inventory reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all reports
  python inventory.py "2026/04 - April/"
  
  # CSV only
  python inventory.py "2026/04 - April/" --csv-only
  
  # Custom output location
  python inventory.py "2026/04 - April/" --output my_inventory
        """
    )
    
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--output", "-o", default="inventory", help="Output filename base")
    parser.add_argument("--csv-only", action="store_true", help="Generate CSV only")
    parser.add_argument("--json-only", action="store_true", help="Generate JSON only")
    
    args = parser.parse_args()
    
    directory = Path(args.directory)
    if not directory.exists():
        parser.error(f"Directory not found: {directory}")
    
    print(f"Scanning: {directory}")
    results = scan_directory(directory)
    
    if not results:
        print("No video files found.")
        return
    
    print(f"Found {len(results)} video files")
    
    base = Path(args.output)
    
    if not args.json_only:
        generate_csv(results, base.with_suffix(".csv"))
    
    if not args.csv_only:
        generate_markdown(results, base.with_suffix(".md"))
    
    generate_json(results, base.with_suffix(".json"))

if __name__ == "__main__":
    main()

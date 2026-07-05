"""
Contact sheet operation - composite thumbnail grids for Claude review.

One 5x6 grid of 320px thumbs carries ~30 clips of visual context in a
single image — the token-efficient way for Claude to actually look at
footage instead of ranking from filenames. Each tile is captioned with
its candidate ID and timecode so verdict JSON can reference tiles
unambiguously.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseOperation, OperationResult

TILE_W = 320
COLS = 5
ROWS = 6
CAPTION_H = 22


def _timecode(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_sheet(tiles: List[Dict[str, Any]], out_path: Path,
                cols: int = COLS, rows: int = ROWS,
                title: Optional[str] = None) -> List[Path]:
    """
    Composite tiles into one or more grid images.

    tiles: [{image: path, caption: str}] — caption is burned under each
    thumb. Returns the sheet paths written (multiple when tiles overflow
    one grid).
    """
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)
    except OSError:
        font = ImageFont.load_default()

    per_sheet = cols * rows
    sheets: List[Path] = []
    tile_h = None

    for page, start in enumerate(range(0, len(tiles), per_sheet)):
        chunk = tiles[start:start + per_sheet]
        images = []
        for tile in chunk:
            img = Image.open(tile["image"]).convert("RGB")
            if img.width != TILE_W:
                img = img.resize((TILE_W, int(img.height * TILE_W / img.width)))
            images.append(img)
        if tile_h is None:
            tile_h = max(i.height for i in images)

        header = 28 if title else 0
        rows_used = (len(chunk) + cols - 1) // cols
        cols_used = min(len(chunk), cols)
        sheet = Image.new("RGB",
                          (cols_used * TILE_W,
                           header + rows_used * (tile_h + CAPTION_H)),
                          (16, 16, 16))
        draw = ImageDraw.Draw(sheet)
        if title:
            draw.text((8, 6), f"{title} — sheet {page + 1}",
                      fill=(255, 255, 255), font=font)

        for i, (img, tile) in enumerate(zip(images, chunk)):
            x = (i % cols) * TILE_W
            y = header + (i // cols) * (tile_h + CAPTION_H)
            sheet.paste(img, (x, y))
            draw.rectangle([x, y + tile_h, x + TILE_W, y + tile_h + CAPTION_H],
                           fill=(30, 30, 30))
            draw.text((x + 4, y + tile_h + 4), tile["caption"][:44],
                      fill=(255, 220, 100), font=font)

        out = (out_path if len(tiles) <= per_sheet
               else out_path.with_stem(f"{out_path.stem}_p{page + 1}"))
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, quality=88)
        sheets.append(out)

    return sheets


def build_candidate_strip(video: Path, start_s: float, end_s: float,
                          out_path: Path, n_frames: int = 8) -> Path:
    """
    Dense tile strip across one candidate's duration — used when Claude
    needs to refine in/out points for a single clip.
    """
    import tempfile
    from ..operations.embed import extract_frame

    step = (end_s - start_s) / max(n_frames - 1, 1)
    tiles = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n_frames):
            ts = start_s + i * step
            frame = Path(tmp) / f"{i}.jpg"
            extract_frame(video, ts, frame, TILE_W)
            tiles.append({"image": str(frame), "caption": _timecode(ts)})
        sheets = build_sheet(tiles, out_path, cols=4, rows=2,
                             title=f"{video.name} {_timecode(start_s)}-{_timecode(end_s)}")
    return sheets[0]


class ContactSheet(BaseOperation):
    """Build a contact-sheet grid from frame thumbnails in context."""

    name = "contact_sheet"
    description = "Composite thumbnail grid for review"
    inputs = ["frames"]
    outputs = ["contact_sheet"]

    def __init__(self, cols: int = COLS, rows: int = ROWS, title: str = ""):
        super().__init__()
        self.cols = cols
        self.rows = rows
        self.title = title

    def execute(self, input_path: Path, output_dir: Path,
                context: Dict[str, Any]) -> OperationResult:
        frames = context.get("frames", [])
        if not frames:
            return OperationResult(success=False,
                                   error="No frames in context (run embed_frames first)")
        tiles = [{"image": f["thumb_path"],
                  "caption": _timecode(f["ts_s"])} for f in frames
                 if f.get("thumb_path")]
        out = Path(output_dir) / f"{input_path.stem}_contact.jpg"
        sheets = build_sheet(tiles, out, self.cols, self.rows,
                             self.title or input_path.name)
        return OperationResult(success=True, output_path=sheets[0],
                               data={"contact_sheets": [str(s) for s in sheets]})

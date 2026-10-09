"""Detector measurements must come from the selected media stream only."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.ffmpeg import analyze_audio_levels, detect_scene_changes, detect_silence


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class DetectorStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ffmpeg(self, *args):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *args],
                       check=True, capture_output=True, timeout=30)

    def test_scenes_use_first_video_not_larger_secondary_stream(self):
        source = self.root / "two-videos.mov"
        self.ffmpeg("-f", "lavfi", "-i", "color=c=black:s=96x64:r=24:d=2",
                    "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=1",
                    "-f", "lavfi", "-i", "color=c=white:s=160x90:r=24:d=1",
                    "-filter_complex", "[1:v][2:v]concat=n=2:v=1:a=0[secondary]",
                    "-map", "0:v", "-map", "[secondary]", "-disposition:v:0", "0",
                    "-disposition:v:1", "default", "-c:v", "mpeg4", str(source))
        scenes, warning = detect_scene_changes(str(source))
        self.assertIsNone(warning)
        self.assertEqual(scenes, [])

    def test_audio_uses_first_track_not_more_channels_on_secondary_track(self):
        source = self.root / "two-audio-tracks.mov"
        self.ffmpeg("-f", "lavfi", "-i", "color=c=black:s=96x64:r=24:d=2",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-ac:a:1", "2",
                    "-disposition:a:0", "0", "-disposition:a:1", "default",
                    "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(source))
        intervals, warning = detect_silence(str(source), duration=2)
        self.assertIsNone(warning)
        self.assertEqual([(row.start, row.end) for row in intervals], [(0, 2)])
        levels, warning = analyze_audio_levels(str(source))
        self.assertIsNone(warning)
        self.assertGreater(len(levels), 0)
        self.assertTrue(all(row.rms_db == -120 for row in levels))

    def test_audio_still_analyzes_when_unselected_video_is_corrupt(self):
        source = self.root / "damaged-video.mov"
        self.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=2",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
                    "-map", "0:v", "-map", "1:a", "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(source))
        packets = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets", "-of", "json", str(source)],
            check=True, capture_output=True, timeout=30).stdout)["packets"]
        packet = packets[len(packets) // 2]
        pos, size = int(packet["pos"]), int(packet["size"])
        data = bytearray(source.read_bytes())
        data[pos:pos + size] = b"\0" * size
        source.write_bytes(data)
        _scenes, warning = detect_scene_changes(str(source))
        self.assertIsNotNone(warning)
        intervals, warning = detect_silence(str(source), duration=2)
        self.assertIsNone(warning)
        self.assertEqual([(row.start, row.end) for row in intervals], [(0, 2)])
        levels, warning = analyze_audio_levels(str(source))
        self.assertIsNone(warning)
        self.assertGreater(len(levels), 0)
        self.assertTrue(all(row.rms_db == -120 for row in levels))


if __name__ == "__main__":
    unittest.main()

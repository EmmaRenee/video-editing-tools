"""Installed OpenCV is not necessarily compatible with the face/person provider."""

from contextlib import redirect_stdout
import importlib.metadata
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.advanced import detect_face_person_presence
from videoedit.cli import main
from videoedit.diagnostics import format_diagnostics, run_diagnostics


class OpenCVCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.footage = self.root / "footage"
        self.footage.mkdir()

    def version(self, versions):
        def lookup(name):
            if name not in versions:
                raise importlib.metadata.PackageNotFoundError(name)
            return versions[name]
        return patch("importlib.metadata.version", side_effect=lookup)

    def spec(self, name):
        return SimpleNamespace(origin="/synthetic/cv2/__init__.py") if name == "cv2" else None

    def diagnose(self):
        report = run_diagnostics(lambda name: f"/synthetic/{name}", self.spec)
        return report, next(row for row in report["optional"] if row["name"] == "cv2")

    def test_opencv5_is_incompatible_but_base_tools_still_work(self):
        with self.version({"opencv-python": "5.0.0.93"}):
            report, cv = self.diagnose()
        self.assertFalse(cv["available"])
        self.assertTrue(cv.get("installed"))
        self.assertEqual(cv.get("status"), "incompatible")
        self.assertIn("opencv-python>=4.8,<5", cv["message"])
        self.assertIn("incompatible", format_diagnostics(report))
        self.assertIn("opencv-python>=4.8,<5", format_diagnostics(report))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["missing_required"], [])

    def test_supported_opencv4_variants_remain_available(self):
        for name in ("opencv-python", "opencv-python-headless", "opencv-contrib-python", "opencv-contrib-python-headless"):
            with self.subTest(name=name), self.version({name: "4.14.0.94"}):
                _report, cv = self.diagnose()
                self.assertTrue(cv["available"])
                self.assertTrue(cv.get("installed"))
                self.assertEqual(cv.get("distributions"), {name: "4.14.0.94"})

    def test_multiple_wheel_variants_are_not_certified_as_compatible(self):
        with self.version({"opencv-python": "4.14.0.94", "opencv-python-headless": "4.14.0.94"}):
            _report, cv = self.diagnose()
        self.assertFalse(cv["available"])
        self.assertIn("multiple", cv["message"].lower())

    def test_old_or_unparseable_wheel_versions_are_not_certified(self):
        for version in ("4.7.0.72", "unknown"):
            with self.subTest(version=version), self.version({"opencv-python": version}):
                _report, cv = self.diagnose()
            self.assertFalse(cv["available"])
            self.assertEqual(cv["status"], "incompatible")

    def test_missing_opencv_reports_optional_remediation(self):
        with self.version({}):
            report = run_diagnostics(lambda name: f"/synthetic/{name}", lambda name: None)
        cv = next(row for row in report["optional"] if row["name"] == "cv2")
        self.assertFalse(cv["available"])
        self.assertFalse(cv["installed"])
        self.assertEqual(cv["status"], "missing")
        self.assertIn("opencv-python>=4.8,<5", cv["message"])
        self.assertEqual(report["status"], "ok")

    def test_unregistered_opencv_retains_unknown_version_and_lazy_import(self):
        original = __import__

        def import_without_cv(name, *args, **kwargs):
            if name == "cv2":
                self.fail("diagnostics must not import OpenCV")
            return original(name, *args, **kwargs)

        with self.version({}), patch("builtins.__import__", side_effect=import_without_cv):
            _report, cv = self.diagnose()
        self.assertTrue(cv["available"])
        self.assertEqual(cv.get("status"), "unverified")
        self.assertEqual(cv.get("distributions"), {})

    def test_modules_doctor_prints_the_install_remediation(self):
        output = StringIO()
        with self.version({"opencv-python": "5.0.0.93"}), patch("importlib.util.find_spec", side_effect=self.spec):
            with redirect_stdout(output):
                self.assertEqual(main(["modules", "doctor"]), 0)
        self.assertIn("opencv-python>=4.8,<5", output.getvalue())

    def test_missing_legacy_detectors_are_unavailable_without_frame_extraction(self):
        cv = SimpleNamespace(__version__="5.0.0", data=SimpleNamespace(haarcascades=""))
        output = self.root / "face.json"
        with patch.dict(sys.modules, {"cv2": cv}), patch("videoedit.advanced.has_command", return_value=True):
            with patch("videoedit.advanced.FrameCache") as sampler:
                sampler.return_value.decoder = {}
                result = detect_face_person_presence(str(self.footage), str(output))
        self.assertEqual(result["status"], "unavailable")
        sampler.assert_not_called()
        report = json.loads(output.read_text())
        self.assertTrue(any("opencv-python>=4.8,<5" in text for text in report["warnings"]))

    def test_broken_cascade_retains_an_actionable_unavailable_artifact(self):
        cascade = self.root / "haarcascade_frontalface_default.xml"
        cascade.touch()

        def broken_classifier(_path):
            raise RuntimeError("invalid cascade")

        cv = SimpleNamespace(__version__="4.14.0", data=SimpleNamespace(haarcascades=str(self.root)),
                             CascadeClassifier=broken_classifier)
        output = self.root / "broken.json"
        with patch.dict(sys.modules, {"cv2": cv}), patch("videoedit.advanced.has_command", return_value=True):
            try:
                result = detect_face_person_presence(str(self.footage), str(output))
            except RuntimeError as exc:
                self.fail(f"provider must retain its unavailable artifact: {exc}")
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(any("invalid cascade" in text for text in json.loads(output.read_text())["warnings"]))


if __name__ == "__main__":
    unittest.main()

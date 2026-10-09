"""Distribution checks must catch omissions, contamination and stale builds."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "smoke" / "audit_distribution.py"


class DistributionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.sources = {
            "videoedit/__init__.py": b'from ._version import __version__\n',
            "videoedit/_version.py": b'__version__ = "0.5.0"\n',
            "videoedit/cli.py": b"def main():\n    return 0\n",
            "LICENSE": b"MIT test license\n", "README.md": b"Public test documentation\n",
            "pyproject.toml": b'[project]\nname = "videoedit"\nversion = "0.5.0"\n',
            "setup.py": b"from setuptools import setup\nsetup()\n",
            "rate_footage.py": b"from videoedit.cli import main\nmain()\n",
        }
        for name, data in self.sources.items():
            path = self.checkout / "src" / "python" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("init", "-q")
        self.git("add", "src/python")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.wheel = self.root / "videoedit-0.5.0-py3-none-any.whl"
        self.sdist = self.root / "videoedit-0.5.0.tar.gz"
        self.wheel_files = {name: data for name, data in self.sources.items() if name.startswith("videoedit/")}
        self.wheel_files.update({
            "videoedit-0.5.0.dist-info/METADATA": b"Metadata-Version: 2.4\nName: videoedit\nVersion: 0.5.0\n",
            "videoedit-0.5.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            "videoedit-0.5.0.dist-info/entry_points.txt": b"[console_scripts]\nvideoedit = videoedit.cli:main\n",
            "videoedit-0.5.0.dist-info/RECORD": b"",
            "videoedit-0.5.0.dist-info/licenses/LICENSE": self.sources["LICENSE"],
        })
        self.sdist_files = {**self.sources, "PKG-INFO": self.wheel_files["videoedit-0.5.0.dist-info/METADATA"]}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.checkout), *args], check=True,
                              capture_output=True, env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
                                                        "GIT_CONFIG_GLOBAL": os.devnull})

    def archives(self):
        with zipfile.ZipFile(self.wheel, "w") as handle:
            for name, data in self.wheel_files.items():
                handle.writestr(name, data)
        with tarfile.open(self.sdist, "w:gz") as handle:
            for name, data in self.sdist_files.items():
                info = tarfile.TarInfo("videoedit-0.5.0/" + name)
                info.size = len(data)
                handle.addfile(info, io.BytesIO(data))

    def audit(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--checkout", str(self.checkout),
                               "--wheel", str(self.wheel), "--sdist", str(self.sdist)],
                              capture_output=True, text=True, timeout=20)

    def rejected(self, code):
        self.archives()
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(code, result.stderr)
        self.assertNotIn(str(self.root), result.stderr)

    def test_clean_distributions_preserve_tracked_runtime_bytes_and_license(self):
        self.archives()
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["runtime_files"], 3)
        self.assertEqual(report["version"], "0.5.0")
        self.assertEqual(len(report["wheel_sha256"]), 64)
        self.assertNotIn(str(self.root), result.stdout)

    def test_untracked_experiments_in_wheel_are_rejected(self):
        self.wheel_files["videoedit/experimental.py"] = b"pass\n"
        self.rejected("unexpected_wheel_member")

    def test_omitted_runtime_file_is_rejected(self):
        del self.wheel_files["videoedit/cli.py"]
        self.rejected("missing_runtime_file")

    def test_stale_or_modified_runtime_bytes_are_rejected(self):
        self.wheel_files["videoedit/cli.py"] = b"def main():\n    return 1\n"
        self.rejected("runtime_bytes_mismatch")

    def test_duplicate_wheel_members_are_rejected(self):
        self.archives()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.wheel, "a") as handle:
                handle.writestr("videoedit/cli.py", self.sources["videoedit/cli.py"])
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate_archive_member", result.stderr)

    def test_unsafe_member_paths_are_rejected(self):
        for name in ("../secret", "/absolute", "videoedit/../secret", "videoedit\\secret.py"):
            with self.subTest(name=name):
                self.wheel_files[name] = b"secret"
                self.rejected("unsafe_archive_member")
                del self.wheel_files[name]

    def test_missing_or_wrong_console_entrypoint_is_rejected(self):
        self.wheel_files["videoedit-0.5.0.dist-info/entry_points.txt"] = b"[console_scripts]\nvideoedit = wrong:main\n"
        self.rejected("invalid_console_entrypoint")

    def test_extra_entrypoints_and_groups_are_rejected(self):
        for extra in (b"private_experiment = videoedit.cli:main\n", b"[videoedit.modules]\nprivate = videoedit.cli:main\n",
                      b"[DEFAULT]\nprivate = videoedit.cli:main\n"):
            with self.subTest(extra=extra):
                self.wheel_files["videoedit-0.5.0.dist-info/entry_points.txt"] = b"[console_scripts]\nvideoedit = videoedit.cli:main\n" + extra
                self.rejected("invalid_console_entrypoint")

    def test_zip_member_types_and_directory_duplicates_are_rejected(self):
        for mode, payload, duplicate in ((0o120777, b"target", False), (0o100644, b"payload", False),
                                         (0o040755, b"", True)):
            with self.subTest(mode=mode, duplicate=duplicate):
                self.archives()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(self.wheel, "a") as handle:
                        member = zipfile.ZipInfo("private-experiment/")
                        member.create_system = 3
                        member.external_attr = mode << 16
                        handle.writestr(member, payload)
                        if duplicate:
                            handle.writestr(member, payload)
                result = self.audit()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("duplicate_archive_member" if duplicate else "unsupported_archive_member", result.stderr)

    def test_license_bytes_are_verified(self):
        self.wheel_files["videoedit-0.5.0.dist-info/licenses/LICENSE"] = b"wrong license"
        self.rejected("license_bytes_mismatch")

    def test_metadata_version_must_match_tracked_package(self):
        self.wheel_files["videoedit-0.5.0.dist-info/METADATA"] = b"Name: videoedit\nVersion: 9.0.0\n"
        self.rejected("metadata_version_mismatch")

    def test_private_or_generated_sdist_files_are_rejected(self):
        for name in (".env", "analysis/ratings.json", "videoedit/cache.pyc", "weights.pt"):
            with self.subTest(name=name):
                self.sdist_files[name] = b"private"
                self.rejected("unexpected_sdist_member")
                del self.sdist_files[name]

    def test_sdist_runtime_bytes_are_also_verified(self):
        self.sdist_files["videoedit/cli.py"] = b"pass\n"
        self.rejected("runtime_bytes_mismatch")

    def test_sdist_retains_tracked_compatibility_scripts(self):
        del self.sdist_files["rate_footage.py"]
        self.rejected("missing_runtime_file")

    def test_sdist_symlink_is_rejected_without_extracting(self):
        self.archives()
        with tarfile.open(self.sdist, "r:gz") as original:
            data = [(row, original.extractfile(row).read()) for row in original.getmembers()]
        with tarfile.open(self.sdist, "w:gz") as handle:
            for info, payload in data:
                handle.addfile(info, io.BytesIO(payload))
            link = tarfile.TarInfo("videoedit-0.5.0/link")
            link.type, link.linkname = tarfile.SYMTYPE, "/private/secret"
            handle.addfile(link)
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported_archive_member", result.stderr)

    def test_worktree_modifications_cannot_be_certified_as_clean_build(self):
        (self.checkout / "src/python/videoedit/cli.py").write_text("changed\n")
        self.rejected("tracked_checkout_modified")

    def test_untracked_source_files_cannot_be_certified_as_clean_build(self):
        (self.checkout / "src/python/videoedit/experiment.py").write_text("pass\n")
        self.rejected("untracked_source_files")


if __name__ == "__main__":
    unittest.main()

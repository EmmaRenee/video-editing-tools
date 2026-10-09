"""Model startup is unnecessary for validated cached scores or unusable frames."""

from contextlib import ExitStack, nullcontext
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from videoedit.ai import OpenCLIPEncoder, score_frames
from videoedit.models import MediaAsset


class Tensor:
    def to(self, _device):
        return self

    def norm(self, **_kwargs):
        return self

    def __truediv__(self, _other):
        return self

    def __matmul__(self, _other):
        return self

    def __rmul__(self, _other):
        return self

    @property
    def T(self):
        return self

    def softmax(self, **_kwargs):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return [[0.7, 0.1, 0.1, 0.1]]


class Model:
    def to(self, _device):
        return self

    def eval(self):
        return self

    def parameters(self):
        return iter([SimpleNamespace(dtype="torch.float32")])

    def encode_image(self, _batch):
        return Tensor()

    def encode_text(self, _tokens):
        return Tensor()


class OpenCLIPLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "one.mp4"
        self.source.write_bytes(b"synthetic provider contract; not video")
        self.checkpoint = self.root / "local.bin"
        self.checkpoint.write_bytes(b"weights-a")
        self.output = self.root / "scores.json"
        self.version = "test-1"
        self.versions = {}
        self.mps = False
        self.sample_hook = lambda: None

        def module(name):
            value = ModuleType(name)
            value.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
            return value

        self.openclip = module("open_clip")
        self.factory = Mock(return_value=(Model(), None, lambda _image: Tensor()))
        self.openclip.create_model_and_transforms = self.factory
        self.openclip.get_tokenizer = lambda _name: lambda _prompts: Tensor()
        self.openclip.get_pretrained_cfg = lambda _model, _pretrained: {"hf_hub": "laion/example/"}
        self.torch = module("torch")
        self.torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: self.mps))
        self.torch.cuda = SimpleNamespace(is_available=lambda: False)
        self.torch.stack = lambda _images: Tensor()
        self.torch.no_grad = nullcontext
        pil = module("PIL")
        pil.Image = SimpleNamespace(open=lambda _path: SimpleNamespace(convert=lambda _mode: object()))
        self.modules = {"open_clip": self.openclip, "torch": self.torch, "PIL": pil}
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.dict(sys.modules, self.modules))
        patches.enter_context(patch("videoedit.ai.library_version", side_effect=lambda name: self.versions.get(name, self.version)))

    def run_scoring(self, input_path=None, **kwargs):
        def sample(_source, _timestamp, output, **_kwargs):
            self.sample_hook()
            Path(output).write_bytes(b"fixture frame")

        return score_frames(str(input_path or self.source), str(self.output), pretrained=str(self.checkpoint),
                            frame_sampler=sample,
                            media_probe=lambda path, **_kwargs: MediaAsset(filename=Path(path).name, filepath=path, duration=1),
                            max_frames_per_file=1, **kwargs)

    def read_scores(self):
        return json.loads(self.output.read_text())

    def no_model_imports(self):
        original = __import__

        def import_metadata_only(name, *args, **kwargs):
            if name in {"open_clip", "PIL"}:
                self.fail(f"cached local checkpoint must not import {name}")
            return original(name, *args, **kwargs)

        return patch("builtins.__import__", side_effect=import_metadata_only)

    def test_local_descriptor_does_not_import_or_initialize_model(self):
        with self.no_model_imports():
            encoder = OpenCLIPEncoder(pretrained=str(self.checkpoint))
        self.factory.assert_not_called()
        self.assertEqual(encoder.device, "cpu")
        self.assertEqual(encoder.precision, "float32")
        self.assertEqual(encoder.provider_version, "test-1")
        self.assertEqual(encoder.checkpoint_path, str(self.checkpoint))
        self.assertIsNone(encoder.model_repository)

    def test_multiple_sources_initialize_one_model(self):
        (self.root / "two.mp4").write_bytes(b"another fixture")
        result = self.run_scoring(self.root)
        self.assertEqual(result["status"], "ok")
        self.factory.assert_called_once()
        self.assertEqual(result["telemetry"].get("models_initialized"), 1)
        self.assertEqual(result["telemetry"].get("model_initialization_attempts"), 1)

    def test_fully_cached_run_imports_no_openclip_and_loads_no_model(self):
        self.run_scoring()
        first = self.read_scores()
        self.factory.reset_mock()
        with self.no_model_imports():
            result = self.run_scoring()
        second = self.read_scores()
        self.factory.assert_not_called()
        self.assertEqual(result["telemetry"]["cache_hits"], 1)
        self.assertEqual(result["telemetry"].get("models_initialized"), 0)
        self.assertEqual(result["telemetry"].get("model_initialization_attempts"), 0)
        self.assertEqual(first["provenance"], second["provenance"])
        self.assertEqual(first["sources"][0]["frames"], second["sources"][0]["frames"])
        self.assertEqual(first["coverage"], second["coverage"])

    def test_one_changed_source_initializes_once_and_preserves_other_cache(self):
        second = self.root / "two.mp4"
        second.write_bytes(b"another fixture")
        self.run_scoring(self.root)
        self.factory.reset_mock()
        second.write_bytes(b"changed fixture media")
        result = self.run_scoring(self.root)
        self.factory.assert_called_once()
        self.assertEqual(result["telemetry"]["cache_hits"], 1)
        self.assertEqual(result["telemetry"]["cache_misses"], 1)
        self.assertEqual(result["telemetry"].get("models_initialized"), 1)

    def test_checkpoint_bytes_library_and_device_still_invalidate(self):
        self.run_scoring()
        previous = self.read_scores()["provenance"]["identity_sha256"]
        stat = self.checkpoint.stat()
        self.checkpoint.write_bytes(b"weights-b")
        os.utime(self.checkpoint, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        for change in (lambda: None, lambda: setattr(self, "version", "test-2"), lambda: setattr(self, "mps", True)):
            change()
            self.factory.reset_mock()
            result = self.run_scoring()
            self.factory.assert_called_once()
            self.assertEqual(result["telemetry"]["cache_misses"], 1)
            self.assertEqual(result["telemetry"].get("models_initialized"), 1)
            current = self.read_scores()["provenance"]["identity_sha256"]
            self.assertNotEqual(previous, current)
            previous = current

    def test_failed_initialization_is_not_retried_per_source(self):
        (self.root / "two.mp4").write_bytes(b"another fixture")
        self.factory.side_effect = RuntimeError("fixture load failure")
        try:
            result = self.run_scoring(self.root)
        except RuntimeError as exc:
            self.fail(f"initialization failure must retain an error artifact: {exc}")
        self.factory.assert_called_once()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["telemetry"].get("models_initialized"), 0)
        self.assertEqual(result["telemetry"].get("model_initialization_attempts"), 1)
        self.assertTrue(all(row["status"] == "error" for row in self.read_scores()["sources"]))

    def test_torch_and_pillow_versions_are_bound_to_cached_scores(self):
        self.run_scoring()
        first = self.read_scores()
        for name in ("torch", "Pillow"):
            with self.subTest(name=name):
                self.versions[name] = "changed-2"
                self.factory.reset_mock()
                result = self.run_scoring()
                self.factory.assert_called_once()
                self.assertEqual(result["telemetry"]["cache_misses"], 1)
                current = self.read_scores()
                self.assertEqual(current["provenance"]["provider"], first["provenance"]["provider"])
                self.assertNotEqual(current["provenance"]["identity_sha256"], first["provenance"]["identity_sha256"])
                self.assertEqual(current["provider_metadata"].get("runtime_libraries", {}).get(name), "changed-2")
                first = current

    def test_reused_encoder_reports_initialization_delta_per_invocation(self):
        encoder = OpenCLIPEncoder(pretrained=str(self.checkpoint))
        first = self.run_scoring(encoder=encoder)
        second = self.run_scoring(encoder=encoder, cache=False)
        self.factory.assert_called_once()
        self.assertEqual(first["telemetry"]["models_initialized"], 1)
        self.assertEqual(second["telemetry"]["models_initialized"], 0)
        self.assertEqual(second["telemetry"]["model_initialization_attempts"], 0)

    def test_named_library_import_failure_retains_install_guidance(self):
        original = __import__

        def broken_import(name, *args, **kwargs):
            if name == "open_clip":
                raise ImportError("fixture broken library")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=broken_import):
            with self.assertRaisesRegex(ImportError, "Install with"):
                OpenCLIPEncoder(pretrained="named-model")

    def test_checkpoint_replacement_during_model_load_cannot_be_cached(self):
        def replace_checkpoint(*_args, **_kwargs):
            self.checkpoint.write_bytes(b"weights-b")
            return Model(), None, lambda _image: Tensor()

        self.factory.side_effect = replace_checkpoint
        result = self.run_scoring()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.read_scores()["frame_count"], 0)
        self.assertTrue(any("checkpoint" in warning for warning in result["warnings"]))

    def test_checkpoint_replacement_before_deferred_load_cannot_be_cached(self):
        self.sample_hook = lambda: self.checkpoint.write_bytes(b"weights-b")
        result = self.run_scoring()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.read_scores()["frame_count"], 0)
        self.assertTrue(any("checkpoint" in warning for warning in result["warnings"]))

    def test_reused_encoder_cannot_claim_new_checkpoint_identity(self):
        encoder = OpenCLIPEncoder(pretrained=str(self.checkpoint))
        self.run_scoring(encoder=encoder)
        self.checkpoint.write_bytes(b"weights-b")
        result = self.run_scoring(encoder=encoder, cache=False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.read_scores()["frame_count"], 0)

    def test_failed_miss_keeps_valid_cache_visible_as_partial(self):
        second = self.root / "two.mp4"
        second.write_bytes(b"another fixture")
        self.run_scoring(self.root)
        second.write_bytes(b"changed fixture media")
        self.factory.reset_mock()
        self.factory.side_effect = RuntimeError("fixture load failure")
        result = self.run_scoring(self.root)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["telemetry"]["cache_hits"], 1)
        self.assertEqual(result["telemetry"]["cache_misses"], 1)
        self.assertEqual(self.read_scores()["frame_count"], 1)
        self.factory.assert_called_once()

    def test_unexpected_loaded_precision_is_not_accepted(self):
        model = Model()
        model.parameters = lambda: iter([SimpleNamespace(dtype="torch.float16")])
        self.factory.return_value = model, None, lambda _image: Tensor()
        result = self.run_scoring()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.read_scores()["frame_count"], 0)
        self.assertTrue(any("precision" in warning for warning in result["warnings"]))

    def test_custom_encoders_do_not_claim_unmeasured_initialization_counts(self):
        encoder = SimpleNamespace(provider_name="custom", model_name="custom-model",
                                  score_images=lambda _paths, _prompts: [[0.7, 0.1, 0.1, 0.1]])
        result = self.run_scoring(encoder=encoder)
        self.assertEqual(result["status"], "ok")
        for key in ("models_initialized", "model_initialization_attempts", "model_initialization_seconds"):
            self.assertIsNone(result["telemetry"][key])

    def test_no_sampled_frames_does_not_initialize(self):
        with patch("videoedit.ai.sample_timestamps", return_value=[]):
            result = self.run_scoring()
        self.assertEqual(result["status"], "error")
        self.factory.assert_not_called()
        self.assertEqual(result["telemetry"].get("models_initialized"), 0)

    def test_named_pretrained_repository_is_resolved_without_model_load(self):
        encoder = OpenCLIPEncoder(pretrained="named-model")
        self.factory.assert_not_called()
        self.assertEqual(encoder.model_repository, "laion/example")

    def test_missing_optional_dependency_stays_actionable(self):
        with patch("importlib.util.find_spec", return_value=None):
            with self.assertRaisesRegex(ImportError, "Install with"):
                OpenCLIPEncoder(pretrained=str(self.checkpoint))


if __name__ == "__main__":
    unittest.main()

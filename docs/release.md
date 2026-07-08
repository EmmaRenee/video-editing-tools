# Release Checklist

This project is local-first. Do not publish a package or GitHub release just because the build passes; publish only after the tool has been exercised on real footage and the release notes accurately describe the current behavior.

## Versioning

- Keep the Python package version in `src/python/videoedit/_version.py`.
- Package metadata reads that version through `src/python/pyproject.toml`.
- Update `CHANGELOG.md` in the same pull request as a version change.
- Use semantic versioning once packages are published:
  - Patch: bug fixes, docs, test hardening.
  - Minor: backward-compatible features or commands.
  - Major: breaking CLI, artifact, or API changes.

## Local Verification

Run these commands from the repository root before opening a release PR:

```bash
python -m pip install --upgrade pip setuptools wheel build
python -m pip install -e ./src/python
python -m unittest discover -s tests/python
git diff --check
python -m build src/python --outdir /tmp/videoedit-dist
python -m venv /tmp/videoedit-wheel-smoke
/tmp/videoedit-wheel-smoke/bin/python -m pip install /tmp/videoedit-dist/videoedit-*.whl
/tmp/videoedit-wheel-smoke/bin/videoedit operations
/tmp/videoedit-wheel-smoke/bin/python -c "import videoedit; print(videoedit.__version__)"
```

Use the repo-local `.venv` only for lightweight package checks. For Torch/OpenCLIP verification, use the local-disk AI environment documented in `INSTALL.md` because synced Google Drive virtual environments can be slow or unreliable for those imports.

## CI Gates

Pull requests and pushes to `main` run `.github/workflows/ci.yml`:

- Python unit tests on Python 3.10, 3.11, and 3.12.
- `git diff --check`.
- Source distribution and wheel build from `src/python`.
- Clean wheel install smoke test using `videoedit operations`.

The base CI path intentionally avoids FFmpeg, Whisper, YOLO, OpenCLIP, cloud credentials, and private footage. Optional-provider checks should remain local/manual or move into separate opt-in workflows.

## GitHub Release Gate

Before drafting a GitHub release:

- Confirm the changelog has a clear section for the release.
- Confirm `videoedit.__version__` matches the intended tag.
- Confirm the release PR merged through green CI.
- Confirm no generated footage, analysis outputs, model weights, wheels, or `dist/` artifacts are staged.
- Attach generated wheels/source distributions only as release assets, not committed files.

## PyPI Gate

PyPI publication is optional and should stay manual until the package is used successfully across real projects.

Before publishing:

- Verify the package name and metadata with a TestPyPI upload first.
- Review optional dependency licensing, especially Ultralytics/YOLO and model-provider packages.
- Confirm no private paths, footage metadata, credentials, or generated analysis artifacts are included in the source distribution.
- Publish with a scoped token from a clean local environment or a dedicated release workflow.

## Generated Artifacts

Do not commit generated media, model weights, analysis folders, package build outputs, or virtual environments. The repository `.gitignore` excludes common outputs including:

- `.venv/`, `venv/`
- `analysis/`, `output/`, `outputs/`, `runs/`
- `*.mp4`, `*.mov`, `*.mkv`, `*.avi`
- `*.pt`, `*.pth`
- `dist/`, `build/`, `*.egg-info/`

If a release needs example artifacts, attach them to a GitHub release or document how to regenerate them.

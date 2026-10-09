# Release Checklist

This project is local-first. Do not publish a package or GitHub release just because the build passes; publish only after the tool has been exercised on real footage and the release notes accurately describe the current behavior.

## Versioning

- V17 candidate proposal: **`0.6.0rc1`**, pending review; no version bump, tag,
  release or publication is authorized by this proposal. Until the real-footage
  and editor gates pass, wheels using the current version are validation builds,
  not a qualified release candidate.
- Keep the Python package version in `src/python/videoedit/_version.py`.
- Package metadata reads that version through `src/python/pyproject.toml`.
- Update `CHANGELOG.md` in the same pull request as a version change.
- Use semantic versioning once packages are published:
  - Patch: bug fixes, docs, test hardening.
  - Minor: backward-compatible features or commands.
  - Major: breaking CLI, artifact, or API changes.

V17 preserves existing V1-V16 command names and accepted JSON shapes. Additive
fields must not require consumers to migrate. Any intentionally incompatible
schema/CLI change requires a documented migration and regression tests before
approval. Core execution remains standard-library Python plus FFmpeg/ffprobe;
AI, vision, UI, cloud and editor adapters remain optional, with explicit
unavailable/partial diagnostics rather than a successful empty result.

## Local Verification

Run these commands from the repository root before opening a release PR:

```bash
python -m pip install --upgrade pip setuptools wheel build
python -m unittest discover -s tests/python
git diff --check
CHECKOUT="$(pwd)"
QUALIFY="$(mktemp -d)"
git archive --format=tar --output "$QUALIFY/source.tar" HEAD
mkdir "$QUALIFY/source"
tar -xf "$QUALIFY/source.tar" -C "$QUALIFY/source"
python -m build "$QUALIFY/source/src/python" --outdir "$QUALIFY/dist"
python tests/smoke/audit_distribution.py --checkout "$CHECKOUT" \
  --wheel "$QUALIFY"/dist/videoedit-*.whl --sdist "$QUALIFY"/dist/videoedit-*.tar.gz
python -m venv "$QUALIFY/wheel"
"$QUALIFY/wheel/bin/python" -m pip install --no-index --no-deps "$QUALIFY"/dist/videoedit-*.whl
cd "$QUALIFY"
"$QUALIFY/wheel/bin/python" -I "$CHECKOUT/tests/smoke/installed_workflow.py" \
  --checkout "$CHECKOUT" --output "$QUALIFY/workflow"
cd "$CHECKOUT"
```

This is a POSIX-shell developer procedure; Windows virtual environments use
`Scripts/python.exe`. Use a clean isolated checkout, not the primary checkout
containing experiments. The auditor refuses modified or untracked `src/python`
files. It checks runtime/compatibility file bytes against Git, rejects unexpected,
duplicate, traversal and symlink archive members, and verifies package version,
the complete approved entrypoint mapping and license. Archive types and duplicate
names are checked before skipping directories. This does not replace human
privacy/license review.

The installed smoke requires FFmpeg/ffprobe and FFmpeg's `libx264`/AAC encoders
for the existing rendered-assembly command. It refuses source/editable imports,
non-venv Python, installed heavy optional providers and a nonempty output folder.
It generates its own small MPEG-4/PCM fixture, then exercises doctor, operations,
modules, inventory, cold/warm rating, review thumbnails/proxies, explicit review
decisions, approval, bounded planning, rendering, EDL/XML export, preset
validation/dry-run and unavailable-provider diagnostics. It checks 30 video
frames / 1.0 second, stereo stream presence and non-zero XML source timecode.
Review must have a complete manifest and actual nonempty thumbnail/proxy files.
Rating must have complete detector status and sampled audio, not merely a
successful process exit or fallback candidate. A successful negative detector
result is distinct from a failed detector. `ratings.json` adds per-source
`analysis_status`/`analysis_complete` and summary `analysis_failed`; failures mark
the rating run partial and are not cached as successes. Older signal artifacts
remain readable, but cached reports without completion evidence are reanalyzed.
Analysis uses FFmpeg's error-fatal mode so decoding errors cannot be concealed by
a successful exit after partial recovery; the installed smoke corrupts a video
packet and verifies partial status with no cache reuse on retry. Caches created
before the fatal-decode policy are invalidated too, even if they recorded success.
`workflow/smoke_report.json` records versions, per-step results/timing and scoped
storage use; stdout/stderr logs remain beside it. Failures produce an incomplete
report after workflow startup. No private media or human annotations are used.

Use the repo-local `.venv` only for lightweight package checks. For Torch/OpenCLIP verification, use the local-disk AI environment documented in `INSTALL.md` because synced Google Drive virtual environments can be slow or unreliable for those imports.

## CI Gates

Pull requests and pushes to `main` run `.github/workflows/ci.yml`:

- Python unit tests on Python 3.10, 3.11, and 3.12.
- `git diff --check`.
- Source distribution and wheel build from `src/python`.
- Wheel/source archive audit against the tracked snapshot.
- Fresh core-only wheel installations on Python 3.10, 3.11 and 3.12, each running
  the synthetic installed workflow outside the checkout with FFmpeg installed.
- Independent CMX/FCP7 readers in their own optional development environment.

Jobs use the explicit `ubuntu-24.04` runner baseline, immutable official action
revisions and a read-only repository token without persisted Git credentials.
The baseline still receives image updates; the smoke report records Python and
media-tool versions rather than claiming a frozen machine. The existing unit
test jobs remain lightweight; only the installed-workflow matrix deliberately
installs FFmpeg. No job installs Whisper, YOLO, OpenCLIP or cloud credentials or
reads private footage. Reports are printed to CI logs; runtime media stays on
the ephemeral runner. Optional-provider installed-state checks remain separately
recorded local/manual evidence, not silently skipped RC acceptance.

Synthetic smoke, archive audits and green CI are necessary but insufficient for
V17 completion. Link independent three-profile benchmarks, provider quality/cost
ablations, approved component dispositions, and actual Resolve original-media
relink/timecode/audio/handle verification under #66/#81 before qualifying the RC.
Reader parsing, audio stream presence and `editor_verified: false` are not editor
or audio-fidelity certification.

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

# V17 Experimental Component Disposition

Inventory date: 2026-10-08. Parent task: #71; consolidation: #72.

The comparison base is `main` at `d8eb36f`. The inspected local checkout
is `feature/shoot-pipeline` at `a0dc644`. Files previously described as
untracked experiments are now committed on that separate branch, but are
not part of the supported `main` package. No files in that checkout were
changed or deleted during this inventory.

## Ownership And Package Boundary

All experiments are repository-authored prototypes. The user retains their
original files; this report approves a disposition, not bulk deletion.
Implementation on `main` uses its existing argparse CLI, callable operation
registry, feature modules, JSON artifacts, and standard-library core.
The separate shoot branch uses Click, `BaseOperation` subclasses, SQLite
shoot records, and a second pipeline runner. Installing both implementations
under the same module names creates ambiguous imports and incompatible
commands. Preserve the current V1-V16 interfaces when reusing an algorithm.

## Disposition

| Component | Purpose And Overlap | Dependencies | Existing Test Status | Disposition And Rationale |
| --- | --- | --- | --- | --- |
| `videoedit/{__init__,cli,pipeline}.py`, `src/python/{setup.py,requirements.txt}` | Alternate top-level frontend, `Pipeline`/`Runner` API and package metadata | Click/PyYAML and optional extras | No preservation tests for all V1-V16 commands | Exclude the replacement frontend/runner; merge provider capabilities through the tracked argparse CLI, existing runner and `pyproject.toml` extras. |
| `videoedit/operations/base.py`, `__init__.py` | Class-based registry conflicts with `videoedit/operations.py` | Python | No focused registry regression suite on the branch | Exclude the second registry; reuse individual algorithms through existing `OperationRegistry` wrappers. |
| `operations/audio_detect.py`, `audio_normalize.py`, `captions.py`, `concatenate.py`, `edl.py`, `extract.py`, `format.py`, `probe.py`, `transcript_detect.py` | Duplicate established analysis and delivery operations | FFmpeg/ffprobe | Legacy standalone scripts and manual use | Merge only independently justified fixes; current V1-V16 operations remain canonical. No bulk promotion. |
| `operations/transcribe.py` | Warm Faster Whisper model cache and transcription fallback | Faster Whisper optional | No dependency-free provider lifecycle tests | Merge model-lifecycle principles under #77 after benchmarks; keep existing `transcribe_whisper` interface. |
| `operations/embed.py` | Batched image embeddings and prompt matching | OpenCLIP, Torch, Pillow optional | No provider ablation evidence | Merge batching/frame reuse principles under #77; preserve existing `score_ai_frames` artifact. |
| `operations/scene.py` | Scene boundaries from PySceneDetect | PySceneDetect optional | No quality comparison against FFmpeg | Defer detector promotion until evidence demonstrates improved boundaries; retain FFmpeg as base. |
| `operations/vad.py` | Speech regions | Silero/Torch optional | No independently annotated speech coverage fixtures | Defer as an optional signal-provider follow-up. |
| `operations/events.py` | Heuristic engine/action audio classification | NumPy/SciPy optional | No cross-project event ground truth | Defer; benchmark before replacing existing motorsports event scoring. |
| `operations/quality.py` | Blur/exposure/frame motion features | OpenCV, Pillow, optional HEIF | No calibration proof for selection value | Defer as an optional technical-quality provider. |
| `operations/contact.py` | Bitmap contact strips | Pillow, FFmpeg | Shoot fixture workflow only | Defer strip export; existing `review_assets.json` and contact sheet remain canonical. |
| `operations/transitions.py` | FFmpeg crossfades | FFmpeg | No mixed-FPS/audio round-trip checks | Defer until #79 establishes timeline semantics and #77 measures render costs. |
| `videoedit/presets.py`, `presets/{ingest,reel,simple,youtube}.yaml` | Second preset definition and loader path | PyYAML on branch | No compatibility checks against `requires_modules` | Exclude alternate discovery; accepted presets must use existing `available_presets` and module contributions. |
| `videoedit/resolve/{api,project,timeline,otio_export}.py`, `__init__.py` | Resolve connection, bins, source import, timeline construction, OTIO export | Resolve and OTIO optional; current exporter depends on ShootDB | Local `test_shoot_otio.py`; live editor verification absent | Promote the capability under #79 through selection/rough-cut adapters. Remove required ShootDB coupling and add start-timecode, audio, mixed-rate and relink tests before support. |
| `videoedit/shoot/{db,scanner,runner}.py` | SQLite inventory, job phases and resumable ingest | SQLite; Click for command frontend | Local DB/scanner tests; not in current `main` CI | Defer full shoot workspace as a separate optional module proposal; harvest safe cache/publication ideas under #77. |
| `shoot/{analyze,candidates,photos,prompts,reports,review,schemas,cli}.py`, `__init__.py` | Shoot-specific analysis funnel, photo culling, review schema and direct Resolve push | Click; vision/audio/HEIF providers optional | Local review/OTIO tests; no V1-V16 compatibility evidence | Defer the independent shoot product surface. Preserve useful schemas as reference for adapters rather than adding a second scoring engine. |
| `videoedit/tui/{app,__init__}.py`, `styles.css`, `screens/{home,browser,builder,runner,operations_list,__init__}.py`, `widgets/{step_editor,__init__}.py` | Rich pipeline builder and runner | Textual/Rich optional | No Textual interaction tests; imports alternate `Pipeline`/`Runner` | Defer pipeline-builder UI; adapt to existing runner/artifacts in its own module if pursued. Existing `review-tui` remains supported. |
| `videoedit/utils/{progress,__init__}.py` | Callback progress tracking | Rich optional | No lifecycle tests | Merge the useful progress/timing behavior into run manifests under #80; avoid making Rich a core dependency. |
| `descript/mcp.py`, `elevenlabs/voiceover.py`, `heygen/avatar.py` | Direct provider execution and legacy setup text | Provider SDKs/network/credentials | No maintained contract/failure tests | Defer execution adapters; current `cloud plan` is the supported credential-safe boundary. |
| `src/python/docs/{examples,operations,resolve}.md` | Docs for alternate command surface | None | Source-only documentation | Archive as branch documentation; promote instructions only with supported commands and validation. |
| `.claude/agents/videoedit-reviewer.md`, `.claude/skills/{pipeline-validator,preset-generator}/SKILL.md` | Agent workflow instructions for alternate pipeline | Claude environment | No supported command contract verification | Defer optional agent integration; retain originals and align with canonical CLI before promotion. |
| `.claude/settings.json`, `.claude/settings.local.json`, `.mcp.json` | Local hooks, permissions and connectors | Machine-specific paths and provider environment | Not package runtime | Exclude from distribution. Inventory only names/key structure; never export credentials or machine configuration. |
| `tests/test_shoot_{db,scanner,review,otio}.py`, `tests/e2e_fixture_shoot.sh`, `tests/fixtures/make_fixtures.sh` | SQLite/scene/shoot/OTIO fixture checks | Branch architecture, FFmpeg; OTIO optional | Not executed as proof of `main` feature support | Merge applicable fixture assertions into focused #79/#77 tests when promoting those capabilities. Preserve original scripts. |

Paths in this table are relative to `src/python/` unless prefixed with
`.claude`, `.mcp.json`, or `tests`. Grouped sets enumerate every runtime
source file discovered in the experimental folders. `__pycache__` and
`*.pyc` are generated interpreter artifacts, not authored implementations.

## Local-Only And Generated Categories

- `analysis/`, `runs/`, `${output}/`, rendered media, proxies, thumbnails,
  source selections, and model weights are private or reproducible outputs.
  Inventory their category only; do not publish names, transcript text, or
  media paths as part of this report.
- `.venv/`, `.pytest_cache/`, `__pycache__/`, `*.pyc`, `.DS_Store*`, local
  agent configuration, and downloaded `yolo26n.pt` are excluded from Git and
  wheels. Exclusion is implemented on the isolated branch, not by deleting
  originals.
- Untracked V1-V16 modules in the local shoot checkout are already tracked
  on `main`; they are not new feature candidates. Their appearance reflects
  the different branch architecture.

## Consolidation Contract

Deferred capabilities have GitHub follow-ups, each with scope, acceptance
criteria, dependencies, and optional-dependency/privacy constraints:

- [#82 Optional scene/speech/audio-event/quality providers](https://github.com/EmmaRenee/video-editing-tools/issues/82).
- [#83 Shoot workspace and photo culling](https://github.com/EmmaRenee/video-editing-tools/issues/83).
- [#84 Pipeline-builder TUI](https://github.com/EmmaRenee/video-editing-tools/issues/84).
- [#85 Bitmap contact strips](https://github.com/EmmaRenee/video-editing-tools/issues/85).
- [#86 Crossfade delivery](https://github.com/EmmaRenee/video-editing-tools/issues/86).
- [#87 Maintained cloud execution adapters](https://github.com/EmmaRenee/video-editing-tools/issues/87).
- [#88 Canonical agent helpers](https://github.com/EmmaRenee/video-editing-tools/issues/88).

These are deferred tasks, not additional V17 release gates or approval to
replace the established package.

1. Keep `videoedit.operations.default_registry` as the single supported
   operation registry and `videoedit.pipeline.available_presets` as the
   single preset path.
2. Use `load_selection` and rough-cut plan artifacts for editor handoff;
   optional OTIO/Resolve code cannot require a shoot database.
3. Import optional SDKs at invocation time and expose missing-dependency
   diagnostics. Core import and `doctor` must work without them.
4. Candidate scoring remains the established rating/calibration system.
   Proposed signal providers produce versioned artifacts and prove their
   value through the V17 benchmark runner.
5. Promotion requires focused behavior tests, docs, wheel-content checks,
   and a focused PR; a file existing on another branch is not support proof.

## Evidence

On the isolated `main` baseline, `python3.12 -m unittest discover -s
tests/python` passed 95 tests. This establishes the base package only.
The primary checkout remains unchanged after discovery. Resolve/OTIO,
provider performance, human annotations, and multi-project validation are
still outstanding and are tracked by their V17 issues.

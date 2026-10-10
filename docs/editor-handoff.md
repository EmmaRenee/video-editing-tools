# Editor Handoff

`videoedit export-edl approved.json --output handoff/` retains its four-file
return contract: CMX EDL, FCP7 XML, VLC M3U and an FFmpeg extraction script.
The additional `*_handoff.json` run manifest embeds `videoedit.handoff.v1`.
Operational outputs contain private media paths; share only explicitly redacted
diagnostics, not the edit files themselves.

## Timing And Relink Contract

- Selections are offsets from the first media frame. Numeric `start_seconds`
  and `end_seconds` override display timestamps. `source_timecode` is separate
  embedded media-start metadata, never an instruction to seek into that hour.
- The source is probed once per unique resolved local path for exact rational
  FPS, duration, dimensions, start timecode and audio streams. An explicit
  `source_fps`, `source_timecode` or `reel` conflicting with the probe or another
  clip from that source is rejected rather than silently accepted.
- The compatibility selection loader interprets SMPTE without `source_fps` at
  document FPS. If probing proves that a file export has a different native rate,
  those bounds are ambiguous: supply explicit `source_fps` or authoritative
  numeric seconds. Export never silently reinterprets existing SMPTE selections.
- Source in/out points round to native frames, nearest with ties upward. Record
  positions accumulate source spans rescaled to timeline FPS and quantized to
  record frames. XML file metadata retains native counters, while clip items
  use timeline-rate counters, matching Resolve's own FCP7 XML representation.
  Decimal NTSC rates use exact `1000/1001` fractions internally.
- EDL uses standard single-line event columns, a deterministic eight-character
  reel, cut-only video events, and a frame-count-mode header. Uniform drop-frame
  media retains drop-frame labels. XML uses media `clipitem`/`file` elements,
  escaped names, percent-encoded file URLs, native file rates, source timecode and
  linked mono/stereo audio when a single supported audio stream is known.
- XML declares a square-pixel sequence canvas at the timeline rate. Canvas
  dimensions follow the first selected source when known; missing dimensions
  stay unspecified for the importing editor to choose. Source dimensions and
  native frame rates remain separate. This sequence-format block is necessary
  for Resolve to import the tracks instead of silently creating an empty edit.
- XML clip `rate`, `in`, `out`, and `duration` use timeline FPS. Native file FPS,
  timecode and full video extent are unchanged. Resolve misinterprets mixed-rate
  native clip counters even when the import mode is Final Cut Pro 7; a 59.94 fps
  EOF clip on a 29.97 fps timeline can otherwise seek beyond its source.
  The manifest separates `source_in_frames`/`source_out_frames` (native) from
  `xml_in_frames`/`xml_out_frames` at `xml_clip_rate`. Matching-rate values are
  unchanged. XML starts round to the nearest timeline frame; the out point is
  that start plus the quantized record duration. At known EOF, the range shifts
  inward to fit whole timeline frames. Ordinary start rounding is at most half
  a timeline frame and end rounding at most one. EOF adjustment can move the
  start inward by up to 1.5 timeline frames. All are relative to the native-snapped
  selection and are reported as
  `xml_start_delta_seconds`/`xml_end_delta_seconds`, with
  `xml_source_range_quantized` and partial status when nonzero. If a full record
  span cannot fit the known video extent, XML fails explicitly; use native OTIO.
  `xml_supported` is false for that case. Do not interpret the XML counters using
  native `source_fps` or treat frame rounding as an editorially approved change.
  For unknown-duration media, the XML file's minimum extent also covers all
  quantized XML out points, rounded upward to native frames. The manifest's
  actual `duration_seconds` remains null; this is not a probed availability claim.
- XML splits a supported stereo stream into linked mono items with explicit
  left/right clip panning. Without that panning, Resolve centers both channels
  and mixes them into identical outputs. Mono sources remain centered, including
  mono clips sharing a timeline track with stereo items. This does not certify
  surround layouts, bus routing, or every editor's audio interpretation.
- Relative source paths preserve an existing current-directory reference;
  otherwise they resolve beside the selection document. If both locations
  contain different media, export fails and requires an absolute path. Symlinks
  resolve to their actual targets. The manifest records the relink mapping.
- A known video-stream duration bounds the selection, including quantized EOF
  endpoints; longer audio/container duration cannot extend video availability.
  When the video extent is unknown, container length is not treated as proof.
  Export rejects out-of-range selection endpoints instead of silently extending
  the source. It does not repair missing historical references.

## Rough-Cut Bounds And Targets

`videoedit roughcut plan approved.json --output roughcut_plan.json --handles 0.5
--target-duration 90 --render-mode render` validates the approved ranges before
adding handles. Invalid approved ranges are rejected, not repaired by clamping.
The planner resolves media paths beside the selection document using the same
ambiguity checks as export, and probes each unique source once per planning call.

Pre-roll stops at zero; post-roll stops at the known video-stream duration.
Every planned clip retains the approved `selection_start_seconds` and
`selection_end_seconds`, `source_duration_seconds`, applied `handles_applied`
(`pre`/`post` seconds), and `handles_clamped_to_source`. Unknown duration remains
null, so post-roll cannot be certified bounded; the plan and run manifest are
`partial`. Native `source_fps`, known source timecode, reels and unsupported edit
features are retained for subsequent delivery and diagnostics.

Targets trim the final retained clip at its elapsed-seconds endpoint, including
sub-second targets and sub-second remainders. `target_trimmed` identifies the
edit; the original approved bounds remain available even if the target trims
approved content. Applied handles are recomputed after trimming. A positive
target producing no source or timeline frame is rejected, not silently extended.
A sub-frame remainder after valid preceding clips is omitted rather than making
the entire plan fail.
Zero duration or zero `max_clips` deliberately produces an empty plan. Handles
and targets must be finite non-negative numbers; `max_clips` must be an integer.

Elapsed planning bounds are not independently snapped to frames. Handoff rounds
to native/record frames as described above, so its quantized duration can differ
from the requested target by frame-rounding tolerances. Rendering/codec timing
and stream-copy keyframes still require separate verification; a plan is not a
completed delivery. `editor_verified` remains false.

## Supported Limits

CMX EDL cannot safely express mixed source rates or mixed DF/NDF modes in this
cut-only writer. Tested CMX rates are 24, 25, 30, 48, 50, 60 and NTSC fractions
24000/1001, 30000/1001, 48000/1001, 60000/1001; other rates, including 120 fps,
are explicitly unsupported rather than emitting invalid frame labels.
Direct `generate_edl` raises a targeted error. The four-file
export instead writes an explicitly **NOT AN IMPORTABLE EDIT** diagnostic EDL
with no edit events, exports XML normally, and marks the manifest `partial` with
`edl_supported: false`. Events beyond CMX numbering/timecode limits are handled
the same way. The CLI prints partial/non-importable warnings while retaining its
successful four-file return contract. Choose XML; do not import the diagnostic
EDL as an empty edit.

EDL exports video only. XML exports one mono or stereo stream; multistream and
surround layouts remain omitted with warnings. Transitions, retiming, effects and
compound clips are not reproduced. Unknown media metadata stays unknown in the
manifest. Offline XML requires a minimum file extent/rate/zero-timecode fallback,
which is explicitly diagnosed rather than reported as probed metadata. Missing
or incomplete metadata and unsupported features produce partial diagnostics.
Equal `r_frame_rate` and `avg_frame_rate` do not certify CFR; source frame-timing
verification remains necessary for variable-rate footage.

M3U start/stop values are numeric seconds, not formatted timecodes. The script
uses precise offsets, but `-c copy` remains keyframe-dependent. Use rendered
extraction/assembly for precise cuts.

## Resolve Import Settings

Use a separate test project before importing into an editorial project. For
CMX EDL, inspect `FCM` and the manifest's `edl_frame_count_mode`. Project/timeline
FPS **and** drop-frame mode must match the EDL, as must the EDL frame-rate and
drop-frame controls in Resolve's import dialog. The header alone does not safely
configure those controls. Matching 29.97 numeric FPS while mixing DF/NDF modes
can offset a cut, leave an EOF clip offline, or fail with a conforming-rate error.
Set this before creating timelines; Resolve can lock project timing settings.

For XML, keep the native media frame rates and use the generated timeline rate;
do not change source clip attributes to force a match. Re-export from Resolve
and compare source/record bounds with the manifest, including rounding deltas.
EDL is video-only; audio Resolve automatically attaches from the media pool is
not evidence that EDL exported audio. Optional OTIO preserves native mixed-rate
source cuts, but Resolve can still quantize their timeline placement on import.

## Optional OTIO Export

```bash
python -m pip install -e "./src/python[editor]"
videoedit modules doctor
videoedit export-otio approved.json --output handoff/edit.otio
videoedit export-otio roughcut_plan.json --output handoff/roughcut.otio --manifest-paths redacted
```

`editor.otio` is optional and can be disabled through `videoedit modules disable
editor.otio`. OpenTimelineIO 0.18.x is supported, with 0.18.1 exercised in CI.
It is loaded only on export; base installation, `doctor`, and the legacy
four-file `export-edl` contract do not require it. Native `.otio` writing needs
no FCP/CMX adapters. The public Python APIs are
`videoedit.otio.export_otio_file(selection_path, output, fps=None,
manifest_paths="absolute")` and `generate_otio(HandoffTimeline, name=...)`.

The same shared loader accepts per-source selections, approved JSON, Drive-style
soundbites and rough-cut plans. `--fps` overrides document FPS, then defaults to
30. Native source FPS stays separate. Output must end in `.otio`. Input/output/
sidecar collisions with the selection or source media are rejected before
writing; a failed atomic output replacement leaves the previous edit intact.

Pipeline operation `generate_otio` accepts one JSON `input`, then falls back to
the current `roughcut_plan` or `approved` context. It returns `output`, `clips`,
`duration_seconds`, `warnings`, and `run_manifest`. The sidecar is named
`<edit-stem>_otio_handoff.json`, separate from legacy XML/EDL handoff reports.
A step with no explicit
output defaults to `<output>/<step-name>.otio`:

```yaml
requires_modules:
  - editor.otio
steps:
  - name: edit
    operation: generate_otio
    input: ${input}
    params:
      output: ${output}/edit.otio
```

The cut-only timeline contains one video track and, when supported audio exists,
one audio track. Media URLs refer to resolved originals, not review proxies.
Each `available_range` starts at the embedded media-start frame, with the full
known native video duration. Each selected `source_range` starts at that origin
plus the selected offset. Unknown availability remains null; a probed duration
is not invented for offline sources. Out-of-range known selections fail.

Source ranges retain integer native frames. Unlike the compatibility XML/EDL
record counters, OTIO track placement accumulates those native durations without
an implicit retime. Mixed-rate placement can therefore land between timeline
frames. `otio.placements` records actual elapsed placement and differences from
the legacy quantized record durations. A nonzero difference produces
`native_duration_differs_from_quantized_record` and partial status, requiring
editor inspection. The sidecar's `handoff` block remains the shared legacy
mapping, not an alternative claim about OTIO track placement.
XML-only rounding or unrepresentability remains in that shared mapping, not
in OTIO's format-specific limitations/status. Exact native OTIO exports do not
become partial solely because a different XML representation would round.

Native source-frame cuts shorter than a timeline frame remain representable in
OTIO even when their legacy record duration rounds to zero. Legacy XML/EDL
minimum-frame validation is unchanged. Redacted sidecars retain the path-free
OTIO placement and quantization diagnostics.

A single known mono/stereo audio stream becomes one audio clip with the same
range as video. Silent or unsupported-audio sources become gaps when an audio
track is present. Surround and multiple streams are not exported; limitations
remain visible. This avoids splitting stereo into centered mono tracks but does
not establish editor channel routing, codec support or linked-selection behavior.
Transitions, retiming, effects and compounds remain omitted with warnings.

Timeline metadata `videoedit.otio.v1` records exact rate strings, source offsets,
embedded timecode, deterministic reel/event identifiers, actual placements,
provider version, limitations and `editor_verified: false`. The run sidecar
fingerprints the `.otio` by content and sources by metadata; it does not claim a
full source-byte checksum. Redaction applies only to the sidecar, **not** the
operational edit's media URLs. Parse/collision validation occurs before manifest
creation to protect inputs; dependency/export failures are recorded once the
manifest safely starts. Keep private edits off public issue attachments.

## Verification

Run the core suite without optional readers:

```bash
python -m unittest discover -s tests/python
```

Independent format checks are also available in an isolated development venv:

```bash
python -m pip install opentimelineio==0.18.1 otio-fcp-adapter==1.0.0 otio-cmx3600-adapter==1.0.0
python -m unittest discover -s tests/python -p test_videoedit_interchange.py
python -m unittest discover -s tests/python -p test_videoedit_otio.py
```

CI runs this separately from core tests and wheel installation. These readers
verify integer/fractional, DF/NDF and mixed-rate XML ranges, media URLs and audio
structure. They do not establish editor codec support, real-media relinking or
audio fidelity. `editor_verified` remains false until a separately recorded live
Resolve import verifies original-media relink, timeline boundaries, timecode,
ordering, handles and audio. Optional OTIO readback validates SDK structure,
native timecode origins, mixed-rate durations, audio gaps, failure behavior and
pipeline compatibility. This does not promote the separate experimental Resolve
SDK integration or prove that every Resolve version interprets the edit equally.

Format references: [Apple FCP7 XML elements](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/FinalCutPro_XML/Elements/Elements.html),
[official OTIO FCP adapter](https://github.com/OpenTimelineIO/otio-fcp-adapter),
[official OTIO CMX adapter](https://github.com/OpenTimelineIO/otio-cmx3600-adapter),
[OTIO timeline/media-time structure](https://opentimelineio.readthedocs.io/en/v0.14/tutorials/otio-timeline-structure.html).

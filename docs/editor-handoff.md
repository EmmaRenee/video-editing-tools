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
  record frames. XML keeps native source counters separate from record counters.
  Decimal NTSC rates use exact `1000/1001` fractions internally.
- EDL uses standard single-line event columns, a deterministic eight-character
  reel, cut-only video events, and a frame-count-mode header. Uniform drop-frame
  media retains drop-frame labels. XML uses media `clipitem`/`file` elements,
  escaped names, percent-encoded file URLs, native rates, source timecode and
  linked mono/stereo audio when a single supported audio stream is known.
- XML declares a square-pixel sequence canvas at the timeline rate. Canvas
  dimensions follow the first selected source when known; missing dimensions
  stay unspecified for the importing editor to choose. Source dimensions and
  native frame rates remain separate. This sequence-format block is necessary
  for Resolve to import the tracks instead of silently creating an empty edit.
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

## Verification

Run the core suite without optional readers:

```bash
python -m unittest discover -s tests/python
```

Independent format checks are also available in an isolated development venv:

```bash
python -m pip install opentimelineio==0.18.1 otio-fcp-adapter==1.0.0 otio-cmx3600-adapter==1.0.0
python -m unittest discover -s tests/python -p test_videoedit_interchange.py
```

CI runs this separately from core tests and wheel installation. These readers
verify integer/fractional, DF/NDF and mixed-rate XML ranges, media URLs and audio
structure. They do not establish editor codec support, real-media relinking or
audio fidelity. `editor_verified` remains false until a separately recorded live
Resolve import verifies original-media relink, timeline boundaries, timecode,
ordering, handles and audio. OTIO is currently a validation dependency only,
not a required runtime dependency or an automatically promoted experimental
Resolve/OTIO integration.

Format references: [Apple FCP7 XML elements](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/FinalCutPro_XML/Elements/Elements.html),
[official OTIO FCP adapter](https://github.com/OpenTimelineIO/otio-fcp-adapter),
[official OTIO CMX adapter](https://github.com/OpenTimelineIO/otio-cmx3600-adapter).

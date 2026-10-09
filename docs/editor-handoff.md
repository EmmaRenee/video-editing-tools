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
- Relative source paths preserve an existing current-directory reference;
  otherwise they resolve beside the selection document. If both locations
  contain different media, export fails and requires an absolute path. Symlinks
  resolve to their actual targets. The manifest records the relink mapping.
- A known video-stream duration bounds the selection, including quantized EOF
  endpoints; longer audio/container duration cannot extend video availability.
  When the video extent is unknown, container length is not treated as proof.
  Export rejects out-of-range
  handles instead of silently extending the source. It does not automatically
  clamp handles or repair missing historical references.

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

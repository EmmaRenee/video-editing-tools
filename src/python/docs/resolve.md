# DaVinci Resolve Integration

Two paths from a rough-cut spec to a Resolve timeline:

| Path | Command | Requires |
|------|---------|----------|
| Direct API (primary) | `videoedit shoot resolve-push <id>` | Resolve **Studio** running, external scripting enabled |
| OTIO file (fallback) | written automatically by `videoedit shoot timeline` | Resolve 17+ (any edition) — File → Import → Timeline |

The `.otio` is always written first, so an API quirk never strands the cut.

## One-time Resolve setup

1. DaVinci Resolve → **Preferences → System → General**
2. Set **"External scripting using"** to **Local**
3. Restart Resolve

The scripting module paths are set automatically on macOS
(`RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`); override the env vars for
non-default install locations. Python must be arm64 on Apple Silicon
(Homebrew python3 is).

## What resolve-push does

1. Connects to the running Resolve and the current (or `--project`) project
2. Creates the bin tree: `A-Roll/Interviews`, `B-Roll/Action`,
   `B-Roll/Atmosphere`, `Photos/Keepers`, `Audio`, `Rejected`
3. Imports every asset referenced by Claude-reviewed candidates,
   keeper photos, and standalone audio
4. Sets clip colors (A-roll = Blue, B-roll = Green, hero photo = Yellow),
   Keywords (CLIP tags), Comments (Claude's notes), Shot (story beats)
5. Creates the timeline and appends clips with per-clip-fps frame math
6. Adds timeline markers from the spec's marker notes

## Manual verification checklist (API tests need a live GUI)

With Resolve Studio running and a scratch project open:

- [ ] `videoedit shoot resolve-push <id>` connects without error
- [ ] Bin tree matches the categories above
- [ ] Clip colors/keywords/comments visible in media pool metadata
- [ ] Timeline cut points match the spec ±1 frame (spot-check 3 clips)
- [ ] Markers appear with the right notes
- [ ] Mixed frame-rate sources (23.976/29.97/59.94) land at correct
      source in/out points
- [ ] Import the sibling `.otio` manually and diff against the API
      timeline — same clip count and durations

## Known quirks

- Resolve must be **running with a project open**; the API cannot launch it.
- `AppendToTimeline` behavior varies slightly across Resolve versions
  (audio track handling, gaps). Re-test after major Resolve upgrades.
- Metadata field names are exact strings ("Keywords", "Comments", "Shot").
- If the same timeline name exists, a ` v2` suffix is appended.

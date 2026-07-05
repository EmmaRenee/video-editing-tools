"""
Resolve - DaVinci Resolve Studio integration.

Primary path: drive a running Resolve Studio instance through its
external Python scripting API (build bins, import media, set
metadata, assemble timelines). Fallback path: export the same
timeline spec as OTIO, which Resolve 17+ imports natively.

The .otio file is always written first — the API push is additive
convenience, so a Resolve quirk never strands the rough cut.
"""

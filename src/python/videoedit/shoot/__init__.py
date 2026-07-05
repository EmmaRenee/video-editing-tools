"""
Shoot - Collection-level processing for whole shoots.

A "shoot" is a directory tree of raw media (video, audio, photos).
This package layers shoot-scale ingest, analysis, and rough-cut
tooling on top of the per-file pipeline system, with a SQLite
database as the contract between phases.
"""
from .db import ShootDB, WORKSPACE_DIRNAME

__all__ = ["ShootDB", "WORKSPACE_DIRNAME"]

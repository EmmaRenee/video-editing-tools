"""
Resolve API bootstrap - connect to a running DaVinci Resolve Studio.

macOS paths for the scripting module are set automatically when the
environment variables are absent. External scripting must be enabled
in Resolve: Preferences → System → General → "External scripting
using: Local".
"""
import os
import sys
from pathlib import Path

MAC_SCRIPT_API = ("/Library/Application Support/Blackmagic Design/"
                  "DaVinci Resolve/Developer/Scripting")
MAC_SCRIPT_LIB = ("/Applications/DaVinci Resolve/DaVinci Resolve.app/"
                  "Contents/Libraries/Fusion/fusionscript.so")


class ResolveConnectionError(RuntimeError):
    pass


def get_resolve():
    """
    Import DaVinciResolveScript and connect to the running Resolve.

    Raises ResolveConnectionError with an actionable message when the
    scripting module is missing, Resolve isn't running, or external
    scripting is disabled.
    """
    api_dir = os.environ.setdefault("RESOLVE_SCRIPT_API", MAC_SCRIPT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", MAC_SCRIPT_LIB)
    modules_dir = str(Path(api_dir) / "Modules")
    if modules_dir not in sys.path:
        sys.path.append(modules_dir)

    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as e:
        raise ResolveConnectionError(
            "Could not import DaVinciResolveScript. Is DaVinci Resolve "
            f"installed? Looked in {modules_dir}. "
            "(On non-default installs, set RESOLVE_SCRIPT_API / "
            "RESOLVE_SCRIPT_LIB.)") from e

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise ResolveConnectionError(
            "Could not connect to DaVinci Resolve. Make sure:\n"
            "  1. Resolve Studio is running\n"
            "  2. Preferences → System → General → "
            "'External scripting using' is set to 'Local'")
    return resolve


def get_project(resolve, project_name=None, create: bool = True):
    """Open (or create) a project by name; default: current project."""
    manager = resolve.GetProjectManager()
    if project_name is None:
        project = manager.GetCurrentProject()
        if project is None:
            raise ResolveConnectionError("No project open in Resolve")
        return project

    project = manager.LoadProject(project_name)
    if project is None and create:
        project = manager.CreateProject(project_name)
    if project is None:
        raise ResolveConnectionError(
            f"Could not open or create project '{project_name}'")
    return project

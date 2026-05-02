"""
Progress utilities for pipeline operations.

Provides progress tracking for long-running operations using rich.
"""
import sys
from typing import Any, Callable, Optional

try:
    from rich.console import Console
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
        TimeRemainingColumn,
    )
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class ProgressTracker:
    """
    Progress tracker for pipeline operations.

    Detects if running in a TTY and uses rich if available,
    otherwise falls back to simple print statements.
    """

    def __init__(self, silent: bool = False):
        """
        Initialize progress tracker.

        Args:
            silent: Disable all output
        """
        self.silent = silent
        self.use_rich = RICH_AVAILABLE and sys.stdout.isatty() and not silent
        self.console = Console() if self.use_rich else None

    def start_step(self, name: str, description: str = "") -> "StepProgress":
        """Start a new step with progress tracking."""
        if self.use_rich:
            return RichStepProgress(name, description, self.console)
        elif not self.silent:
            return SimpleStepProgress(name, description)
        else:
            return SilentStepProgress(name, description)


class StepProgress:
    """Base class for step progress tracking."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def update(self, advance: int = 1, total: int | None = None):
        """Update progress."""
        pass

    def complete(self, message: str = "Complete"):
        """Mark step as complete."""
        pass

    def error(self, message: str):
        """Report an error."""
        pass


class RichStepProgress(StepProgress):
    """Rich progress bar for a single step."""

    def __init__(self, name: str, description: str, console: "Console"):
        super().__init__(name, description)
        self.console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        )
        self.task_id = None

    def __enter__(self):
        self.progress.__enter__()
        desc = self.description or self.name
        self.task_id = self.progress.add_task(f"[{self.name}] {desc}", total=None)
        return self

    def __exit__(self, *args):
        self.progress.__exit__(*args)

    def update(self, advance: int = 1, total: int | None = None):
        """Update progress."""
        if self.task_id is not None:
            if total is not None:
                self.progress.update(self.task_id, total=total)
            self.progress.advance(self.task_id, advance)

    def complete(self, message: str = "Complete"):
        """Mark step as complete."""
        if self.task_id is not None:
            self.progress.update(self.task_id, completed=100 if self.progress.tasks[0].total is None else self.progress.tasks[0].total)
        self.console.print(f"[green]✓[/green] [{self.name}] {message}")

    def error(self, message: str):
        """Report an error."""
        self.console.print(f"[red]✗[/red] [{self.name}] {message}")


class SimpleStepProgress(StepProgress):
    """Simple text progress for non-TTY or when rich unavailable."""

    def __init__(self, name: str, description: str):
        super().__init__(name, description)
        print(f"[{self.name}] {description or 'Starting...'}")

    def update(self, advance: int = 1, total: int | None = None):
        """Update progress (no-op for simple)."""
        pass

    def complete(self, message: str = "Complete"):
        """Mark step as complete."""
        print(f"✓ [{self.name}] {message}")

    def error(self, message: str):
        """Report an error."""
        print(f"✗ [{self.name}] {message}")


class SilentStepProgress(StepProgress):
    """Silent progress for batch mode."""

    def complete(self, message: str = "Complete"):
        pass

    def error(self, message: str):
        print(f"[{self.name}] {message}", file=sys.stderr)

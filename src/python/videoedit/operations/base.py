"""
Base operation class for all video processing operations.

All operations inherit from BaseOperation and implement the execute() method.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class OperationResult:
    """Result of an operation execution."""
    success: bool
    output_path: Optional[Path] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


class BaseOperation(ABC):
    """Base class for all video processing operations."""

    name: str = ""
    description: str = ""
    inputs: list[str] = []
    outputs: list[str] = []

    def __init__(self, **params):
        self.params = params
        self.result_data = {}

    @abstractmethod
    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """
        Execute the operation.

        Args:
            input_path: Path to input file or directory
            output_dir: Directory for outputs
            context: Shared context from previous operations (transcripts, segments, etc.)

        Returns:
            OperationResult with success status and output data
        """
        pass

    def validate_params(self) -> bool:
        """Validate parameters before execution."""
        return True

    def get_output_path(self, output_dir: Path, suffix: str = "") -> Path:
        """Generate an output path based on input and suffix."""
        return output_dir / f"{self.name}{suffix}"

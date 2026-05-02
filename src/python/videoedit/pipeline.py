"""
Pipeline - Core classes for building and running video processing pipelines.

Pipelines are chains of operations that process video files.
They can be built programmatically or loaded from YAML files.
"""
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

from .operations.base import BaseOperation, OperationResult
from .utils.progress import ProgressTracker


@dataclass
class Step:
    """A single step in a pipeline."""
    name: str
    operation: str
    params: Dict[str, Any] = field(default_factory=dict)
    input_from: Optional[str] = None  # Name of step to get input from

    def __post_init__(self):
        if not self.operation:
            self.operation = self.name


class Pipeline:
    """
    A video processing pipeline.

    Pipelines are chains of operations that process video files sequentially.
    Each operation can pass data to the next via the shared context.
    """

    def __init__(self, name: str = "", description: str = ""):
        self.name = name or f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.description = description
        self.steps: List[Step] = []

    def add(self, operation: str, name: Optional[str] = None,
            input_from: Optional[str] = None, **params) -> "Pipeline":
        """
        Add a step to the pipeline.

        Args:
            operation: Name of the operation class (e.g., "transcribe_whisper")
            name: Optional name for this step (defaults to operation name)
            input_from: Optional step name to use as input
            **params: Parameters to pass to the operation

        Returns:
            self for chaining
        """
        step = Step(
            name=name or operation,
            operation=operation,
            params=params,
            input_from=input_from
        )
        self.steps.append(step)
        return self

    def remove(self, name: str) -> bool:
        """Remove a step by name."""
        for i, step in enumerate(self.steps):
            if step.name == name:
                self.steps.pop(i)
                return True
        return False

    def get_step(self, name: str) -> Optional[Step]:
        """Get a step by name."""
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert pipeline to dictionary for YAML serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "steps": [
                {
                    "name": s.name,
                    "operation": s.operation,
                    "params": s.params,
                    "input": s.input_from
                }
                for s in self.steps
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pipeline":
        """Create pipeline from dictionary (YAML parsed)."""
        pipeline = cls(
            name=data.get("name", ""),
            description=data.get("description", "")
        )
        for step_data in data.get("steps", []):
            step = Step(
                name=step_data.get("name", step_data["operation"]),
                operation=step_data["operation"],
                params=step_data.get("params", {}),
                input_from=step_data.get("input")
            )
            pipeline.steps.append(step)
        return pipeline


class Runner:
    """
    Executes pipelines on video files.

    Handles loading operations, running steps, and managing shared context.
    """

    def __init__(self, pipeline: Pipeline, work_dir: Optional[Path] = None, progress: Optional[ProgressTracker] = None):
        """
        Initialize runner.

        Args:
            pipeline: Pipeline to run
            work_dir: Working directory for intermediate files
            progress: Progress tracker (uses default if not provided)
        """
        self.pipeline = pipeline
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.progress = progress or ProgressTracker()
        self.results: Dict[str, OperationResult] = {}
        self.context: Dict[str, Any] = {}
        self._operation_cache: Dict[str, type[BaseOperation]] = {}

    def _load_operation(self, operation_name: str) -> type[BaseOperation]:
        """Dynamically load an operation class."""
        if operation_name in self._operation_cache:
            return self._operation_cache[operation_name]

        # Try to import from operations module
        # Convert "transcribe_whisper" to "TranscribeWhisper"
        class_name = "".join(word.capitalize() for word in operation_name.split("_"))

        try:
            module = importlib.import_module(f".operations.{operation_name.split('_')[0]}", package="videoedit")
            op_class = getattr(module, class_name, None)

            if op_class is None:
                # Try snake_case class name
                op_class = getattr(module, operation_name, None)

            if op_class and issubclass(op_class, BaseOperation):
                self._operation_cache[operation_name] = op_class
                return op_class
        except (ImportError, AttributeError):
            pass

        raise ValueError(f"Operation not found: {operation_name}")

    def run(self, input_path: Union[str, Path], output_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """
        Run the pipeline on an input file.

        Args:
            input_path: Path to input video file
            output_dir: Directory for outputs (defaults to work_dir/output)

        Returns:
            Dictionary with final results and context
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Input not found: {input_path}")

        output_dir = Path(output_dir) if output_dir else self.work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        self.context["input_file"] = input_path
        self.context["output_dir"] = output_dir

        for step in self.pipeline.steps:
            step_progress = self.progress.start_step(step.name, step.operation)

            try:
                op_class = self._load_operation(step.operation)
                operation = op_class(**step.params)

                # Determine input path for this step
                step_input = input_path
                if step.input_from and step.input_from in self.results:
                    prev_result = self.results[step.input_from]
                    if prev_result.output_path:
                        step_input = prev_result.output_path

                # Execute step
                result = operation.execute(step_input, output_dir, self.context)
                self.results[step.name] = result

                # Update context with result data
                if result.data:
                    self.context.update(result.data)

                if result.success:
                    msg = f"Output: {result.output_path}" if result.output_path else "Complete"
                    step_progress.complete(msg)
                else:
                    step_progress.error(result.error)
                    raise RuntimeError(f"Step '{step.name}' failed: {result.error}")

            except Exception as e:
                step_progress.error(str(e))
                raise

        return {
            "success": True,
            "context": self.context,
            "results": {name: r.data for name, r in self.results.items()}
        }

# VideoEdit Code Reviewer

Specialized subagent for reviewing videoedit package changes.

## Focus Areas

### Pipeline Operations
- Operation classes inherit from BaseOperation correctly
- execute() method returns OperationResult with proper fields
- Parameter validation matches documented schema
- Error handling covers FFmpeg failures

### CLI Commands
- Click decorators use consistent patterns
- Help text is clear and accurate
- Command names follow conventions (lowercase, hyphens)
- Error messages are user-friendly

### YAML Presets
- Pipeline YAML matches schema (name, description, steps)
- Operation names are valid snake_case
- Parameter names match operation __init__ signatures
- Step input references are valid

### FFmpeg Commands
- Codec names are correct (libx264, prores_ks, etc.)
- Filter syntax is valid (vf, af filters)
- Output formats match intended use (EDL, SRT, MP4)
- Scaling uses safe values (-2 for even dimensions)

## Review Checklist

- [ ] New operations follow existing patterns in operations/
- [ ] CLI command added to cli.py with proper Click decorators
- [ ] Preset YAML added to presets/ with .yaml extension
- [ ] FFmpeg commands tested for syntax correctness
- [ ] Error handling covers common failures (file not found, FFmpeg errors)
- [ ] Documentation updated (SKILL.md, README.md, or docstrings)

## Common Issues

| Issue | Fix |
|-------|-----|
| Missing OperationResult import | Add: from .operations.base import OperationResult |
| FFmpeg path escaping | Use raw strings or proper escaping for filters |
| YAML input field | Should be `input:` not `input_from:` in pipeline YAML |
| Click option ordering | @click.option before @click.argument |
| Missing success/error in result | OperationResult must have success, error, output_path, data |

## Code Patterns

### Operation Class Template

```python
"""
Module docstring.
"""
from pathlib import Path
from typing import Dict, Any
from .base import BaseOperation, OperationResult

class MyOperation(BaseOperation):
    """One-line description."""

    def __init__(self, param1: str = "default", param2: int = 10):
        self.param1 = param1
        self.param2 = param2

    def execute(self, input_path: Path, output_dir: Path, context: Dict[str, Any]) -> OperationResult:
        """Execute the operation.

        Args:
            input_path: Path to input file
            output_dir: Directory for outputs
            context: Shared pipeline context

        Returns:
            OperationResult with success status
        """
        try:
            # Implementation here
            output_path = output_dir / "output.mp4"

            return OperationResult(
                success=True,
                output_path=output_path,
                data={"key": "value"}
            )
        except Exception as e:
            return OperationResult(
                success=False,
                error=str(e)
            )
```

### CLI Command Template

```python
@cli.command()
@click.argument("input_file")
@click.option("--output", "-o", help="Output directory")
def my_command(input_file, output):
    """Command description."""
    from .operations.my_operation import MyOperation

    op = MyOperation()
    result = op.execute(Path(input_file), Path(output or "./output"), {})

    if result.success:
        click.echo(f"Success: {result.output_path}")
    else:
        click.echo(f"Error: {result.error}", err=True)
        sys.exit(1)
```

### Preset YAML Template

```yaml
name: Preset Name
description: One-line description
steps:
  - name: step_name
    operation: operation_name
    params:
      key: value
  - name: dependent_step
    operation: another_operation
    input: step_name  # References previous step
    params:
      key: value
```

## Testing Recommendations

1. Test FFmpeg commands manually before coding
2. Validate YAML with `videoedit validate preset.yaml`
3. Test operations with sample video files
4. Check error handling with invalid inputs

## Files of Interest

- `src/python/videoedit/operations/` - Operation implementations
- `src/python/videoedit/cli.py` - CLI commands
- `src/python/videoedit/presets/` - YAML presets
- `src/python/videoedit/pipeline.py` - Pipeline core
- `src/python/videoedit/presets.py` - Preset registry

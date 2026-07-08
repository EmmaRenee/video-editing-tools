# Community Modules

Community modules extend `videoedit` through the `videoedit.modules` Python entry point group. They can contribute operations, pipeline presets, diagnostics, and optional provider checks without changing core package code.

## Start From The Scaffold

```bash
videoedit modules scaffold my_feature --output videoedit-my-feature/
cd videoedit-my-feature
python -m pip install -e .
videoedit modules list
videoedit modules doctor
videoedit operations
videoedit init my_feature_example --output my_feature_example.yaml
```

The generated package includes a module entry point, an example operation, diagnostics, a preset, tests, and compatibility notes.

## Module IDs

Use stable dotted IDs:

- `community.shop_reports`
- `community.caption_qc`
- `advanced.my_detector`

Do not use `core.*`, duplicate built-in module IDs, or change IDs between releases. Project configs store enabled and disabled modules by ID.

## Entry Point Contract

In `pyproject.toml`:

```toml
[project.entry-points."videoedit.modules"]
my_feature = "my_feature.module:get_module"
```

`get_module()` must return a mapping or `FeatureModule` with:

- `id`: stable dotted module ID.
- `description`: reader-facing purpose.
- `category`: usually `community`, `advanced`, `delivery`, or `content`.
- `operations`: optional list of operation mappings with `name`, `description`, and callable `func`.
- `presets`: optional mapping of preset name to pipeline YAML-like mappings.
- `diagnostics`: optional callable returning `{ "module": "...", "checks": [...] }`.

Operations should use unique names, preferably prefixed by the package name. Do not override built-in operation names.

## Optional Dependencies

Keep imports lightweight. Package import and `get_module()` should not fail when an optional model, SDK, binary, or service is missing. Report availability through diagnostics instead:

```python
def diagnose():
    return {
        "module": "community.my_feature",
        "checks": [
            {"name": "my_binary", "type": "command", "available": False, "message": "Install my_binary"}
        ],
    }
```

## Artifact Compatibility

Operations should read and write JSON-first artifacts. New artifact schemas should include:

- `schema_version`
- `artifact_kind`
- provider or module metadata where useful
- stable source path fields when artifacts reference footage
- compact summaries for review and diagnostics

Do not write private footage, credentials, API keys, or raw personal contact/payment details into artifacts.

## Presets

Presets should declare `requires_modules`. External presets automatically receive their owning module ID if it is missing, but explicit declarations are clearer:

```python
"presets": {
    "my_feature_example": {
        "name": "my_feature_example",
        "requires_modules": ["community.my_feature"],
        "steps": [{"name": "example", "operation": "my_feature_example"}],
    }
}
```

Disabled modules hide their presets from `videoedit init`; validation fails clearly if a pipeline requires a disabled or unavailable module.

## Required Tests

Community packages should test:

- module metadata and entry point discovery
- optional dependency diagnostics
- operation output shape and schema version
- preset registration and validation
- missing dependency behavior
- artifact compatibility with existing `videoedit` JSON conventions

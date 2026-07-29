# Contributing

Contributions should preserve local-only operation and the default read-only
safety model.

- Remove credentials, private endpoints, Home Assistant diagnostics, device
  identifiers, and bar codes from reports and fixtures.
- Do not submit vendor binaries, decompiled vendor source, or copyrighted
  protocol PDFs.
- Add Home Assistant runtime tests for config flow, coordinator, entity, or
  diagnostics changes.
- Protocol changes belong in
  [`huawei-esm48100`](https://github.com/GImDX/huawei-esm48100).

Run the repository checks before opening a pull request:

```bash
python -m pip install -r requirements-test.txt
python -m ruff check .
python -m pytest
```

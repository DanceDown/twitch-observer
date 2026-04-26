# Development

This document describes local developer tooling that is intentionally kept out of the default runtime image.

## Ruff

Ruff is the project's Python linter. It checks for common Python mistakes, unused code, import ordering, and small simplifications.

The active rule set is configured in [ruff.toml](../ruff.toml).

### Run Ruff in Docker

Build the app image with development dependencies:

```powershell
$env:INSTALL_DEV = "true"
docker compose build app
```

Run the lint check:

```powershell
docker compose run --rm app python -m ruff check src
```

Apply safe auto-fixes:

```powershell
docker compose run --rm app python -m ruff check src --fix
```

Check formatting without changing files:

```powershell
docker compose run --rm app python -m ruff format src --check
```

Apply Ruff formatting only when you intentionally want a formatting-only diff:

```powershell
docker compose run --rm app python -m ruff format src
```

### Run Ruff Locally

Install development dependencies in your local Python environment:

```powershell
python -m pip install -r requirements-dev.txt
```

Then run:

```powershell
python -m ruff check src
```

### Deployment

Ruff is a development dependency only. The default Docker build uses `INSTALL_DEV=false`, which installs only [requirements.txt](../requirements.txt).

Before building a deployment image, unset or disable the development flag:

```powershell
Remove-Item Env:INSTALL_DEV -ErrorAction SilentlyContinue
docker compose build app
```

Or set it explicitly:

```powershell
$env:INSTALL_DEV = "false"
docker compose build app
```

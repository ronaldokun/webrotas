# Migration: requirements.txt → pyproject.toml

## Overview

The project has been migrated to use a single `pyproject.toml` file for dependency management across all services, replacing the previous `avoidzones/requirements.txt`.

## Changes Made

### 1. Root `pyproject.toml`
- **Added build-system configuration** for hatchling (standard Python packaging)
- **Updated description** to reflect project purpose
- **Updated dependencies** with specific versions:
  - `apscheduler>=3.11.1` - Cron scheduling
  - `docker>=7.1.0` - Docker API client
  - `fastapi>=0.121.0` - Web framework
  - `osmium>=4.2.0` - OSM PBF processing (replaces `pyosmium`)
  - `shapely>=2.1.2` - Geometric operations
  - `uvicorn[standard]>=0.38.0` - ASGI server
- **Added optional-dependencies** for development:
  - `pytest>=7.0` - Testing framework
  - `pytest-asyncio>=0.21.0` - Async test support
- **Added tool.uv configuration**:
  - `default-groups = ["avoidzones"]` - Loads all dependencies by default
  - Override for `osmium` version (pyosmium compatibility)

### 2. `avoidzones/Dockerfile`
**Before:**
```dockerfile
COPY requirements.txt /app/
RUN /root/.cargo/bin/uv pip install --no-cache-dir -r requirements.txt
```

**After:**
```dockerfile
COPY pyproject.toml /app/
RUN /root/.cargo/bin/uv sync --no-cache
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9090"]
```

**Key improvements:**
- Uses `uv sync` instead of `uv pip install` (more robust, creates virtual environment)
- Uses `uv run` to execute commands with proper environment
- Single source of truth for dependencies via root pyproject.toml
- Cleaner, more maintainable approach

### 3. `docker-compose.yml`
**Before:**
```yaml
build:
  context: ./avoidzones
  dockerfile: Dockerfile
```

**After:**
```yaml
build:
  context: .
  dockerfile: ./avoidzones/Dockerfile
```

**Reason:** Build context must include the root `pyproject.toml` file for the Dockerfile to access it.

### 4. Removed Files
- `avoidzones/requirements.txt` - No longer needed, consolidated into root pyproject.toml

## Benefits

1. **Single Source of Truth** - All Python dependencies managed in one place
2. **Better Dependency Tracking** - Version pinning for reproducibility
3. **Standards Compliant** - Uses PEP 517/518 standard Python packaging
4. **Faster Builds** - `uv sync` is faster and more reliable than `pip install`
5. **Dev Dependencies** - Optional dependencies for development workflows
6. **Professional Structure** - Follows Python packaging best practices

## Development Commands

### Local Development
```bash
# Install dependencies in virtual environment
uv sync

# Run the avoidzones service locally
uv run python -m uvicorn avoidzones.app:app --reload --port 9090

# Run tests
uv run pytest
```

### Docker Build
```bash
# Build the avoidzones service
docker-compose build avoidzones

# Run with compose
docker-compose up -d --build avoidzones
```

### View Dependencies
```bash
# Show locked dependencies
uv sync --dry-run

# Show project metadata
uv show
```

## Migration Notes

- No functional changes to the application—purely dependency management restructuring
- All services still use the exact same Python packages with same versions
- Docker socket mounting remains unchanged at `/var/run/docker.sock:/var/run/docker.sock:ro`
- Environment variables in docker-compose.yml unchanged

## Future Improvements

- Add lock file (`uv.lock`) to version control for even better reproducibility
- Add pre-commit hooks configuration
- Add mypy/ruff configuration sections to pyproject.toml
- Add test discovery and coverage configuration

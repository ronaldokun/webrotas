FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Build dependencies for shapely/pyosmium compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ libproj-dev proj-data proj-bin curl \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Disable Python downloads, because we want to use the system interpreter
# across both images. If using a managed Python version, it needs to be
# copied from the build image into the final image; see `standalone.Dockerfile`
# for an example.
ENV UV_PYTHON_DOWNLOADS=0

# Set working directory
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev


COPY pyproject.toml uv.lock ./
COPY src/ ./src
COPY README.md README.md


RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.13-slim-bookworm

# Install system dependencies for osmium and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 libproj25 proj-data libc6 \
    && rm -rf /var/lib/apt/lists/*

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Create /data directory and set permissions for nonroot user
RUN mkdir -p /data && chown -R nonroot:nonroot /data

# Use the non-root user to run our application
USER nonroot

# Use `/app` as the working directory
WORKDIR /app


# Expose port
EXPOSE 9090

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run FastAPI application
CMD ["uvicorn", "webrotas.app:app", "--host", "0.0.0.0", "--port", "9090"]

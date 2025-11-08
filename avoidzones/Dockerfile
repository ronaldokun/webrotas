FROM ghcr.io/project-osrm/osrm-backend:latest

# Python + build deps for shapely/pyosmium
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv g++ libproj-dev proj-data proj-bin curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
COPY requirements.txt /app/
RUN /root/.cargo/bin/uv pip install --no-cache-dir -r requirements.txt

COPY app.py cutter.py /app/

EXPOSE 9090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9090"]

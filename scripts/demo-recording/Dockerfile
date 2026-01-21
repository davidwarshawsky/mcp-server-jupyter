# Custom code-server image with Python and MCP dependencies
FROM lscr.io/linuxserver/code-server:latest

# Install Python and required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install MCP server Python dependencies (from pyproject.toml)
RUN pip3 install --break-system-packages \
    "mcp>=1.0.0,<2.0.0" \
    "jupyter_client>=8.0.0,<9.0.0" \
    "nbformat>=5.0.0,<6.0.0" \
    "ipykernel>=6.0.0,<7.0.0" \
    "psutil>=5.9.0,<6.0.0" \
    "GitPython>=3.1.0,<4.0.0" \
    "uvicorn[standard]>=0.40.0,<1.0.0" \
    "starlette>=0.51.0,<1.0.0" \
    "websockets>=14.0,<15.0" \
    "structlog>=24.1.0,<25.0.0" \
    "pydantic>=2.0.0,<3.0.0" \
    "aiofiles>=23.2.0,<24.0.0" \
    "loguru>=0.7.0,<1.0.0" \
    "opentelemetry-api>=1.22.0,<2.0.0" \
    "opentelemetry-sdk>=1.22.0,<2.0.0" \
    "opentelemetry-exporter-otlp>=1.22.0,<2.0.0" \
    "duckdb>=1.1.0,<2.0.0" \
    pandas \
    anyio \
    httpx

# Create symlink for python command
RUN ln -sf /usr/bin/python3 /usr/bin/python

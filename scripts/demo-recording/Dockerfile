# ==============================================================================
# MCP Jupyter Demo Recording Environment
# ==============================================================================
# 
# Custom code-server image with Python and all MCP dependencies pre-installed.
# Used for Playwright-based demo recording automation.
#
# Build:    docker compose build
# Run:      docker compose up -d
# Access:   http://localhost:8443
#
# ==============================================================================

FROM lscr.io/linuxserver/code-server:latest

# Metadata
LABEL maintainer="MCP Jupyter Team"
LABEL description="Demo recording environment for MCP Jupyter"
LABEL version="1.0.0"

# Install Python and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create symlink for python command
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install MCP server Python dependencies (from pyproject.toml)
# These are pinned to specific version ranges for reproducibility
RUN pip3 install --break-system-packages \
    # Core MCP dependencies
    "mcp>=1.0.0,<2.0.0" \
    # Jupyter kernel management
    "jupyter_client>=8.0.0,<9.0.0" \
    "nbformat>=5.0.0,<6.0.0" \
    "ipykernel>=6.0.0,<7.0.0" \
    # System utilities
    "psutil>=5.9.0,<6.0.0" \
    "GitPython>=3.1.0,<4.0.0" \
    # ASGI/WebSocket server
    "uvicorn[standard]>=0.40.0,<1.0.0" \
    "starlette>=0.51.0,<1.0.0" \
    "websockets>=14.0,<15.0" \
    # Logging and validation
    "structlog>=24.1.0,<25.0.0" \
    "pydantic>=2.0.0,<3.0.0" \
    "aiofiles>=23.2.0,<24.0.0" \
    "loguru>=0.7.0,<1.0.0" \
    # Observability
    "opentelemetry-api>=1.22.0,<2.0.0" \
    "opentelemetry-sdk>=1.22.0,<2.0.0" \
    "opentelemetry-exporter-otlp>=1.22.0,<2.0.0" \
    # Superpowers
    "duckdb>=1.1.0,<2.0.0" \
    # Data science essentials (for demos)
    pandas \
    numpy \
    matplotlib \
    seaborn \
    # Async utilities
    anyio \
    httpx

# Install ipykernel to register Python kernel
RUN python3 -m ipykernel install --user --name python3 --display-name "Python 3"

# Pre-create directories that VS Code will need
RUN mkdir -p /config/workspace \
    && mkdir -p /config/data/User/globalStorage \
    && mkdir -p /config/extensions

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8443/healthz || exit 1

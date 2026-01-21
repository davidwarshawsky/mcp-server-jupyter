# Custom code-server image with Python and MCP dependencies
FROM lscr.io/linuxserver/code-server:latest

# Install Python and required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install MCP server Python dependencies
RUN pip3 install --break-system-packages \
    mcp \
    jupyter_client \
    nbformat \
    ipykernel \
    psutil \
    GitPython \
    uvicorn \
    websockets \
    duckdb \
    pandas \
    starlette \
    anyio \
    httpx

# Create symlink for python command
RUN ln -sf /usr/bin/python3 /usr/bin/python

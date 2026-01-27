FROM python:3.10-slim

# 1. Install build dependencies and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    libmagic1 \
    # [ZOMBIE FIX] Add fuser for port cleanup
    psmisc \
    # [LOCK CLEANUP] Add find utility (usually present)
    findutils \
    && rm -rf /var/lib/apt/lists/*

# NOTE: We do not install cluster tooling (e.g., kubectl) in the server image by default. Port-forwarding
# via subprocess is brittle; prefer direct pod networking (sidecar/proxy) in production.

WORKDIR /app

# 2. Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# 3. Copy only necessary files
COPY --chown=appuser:appuser tools/mcp-server-jupyter/ /app

# 4. [ZOMBIE FIX] Copy entrypoint script with proper permissions
COPY --chown=appuser:appuser tools/mcp-server-jupyter/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 5. Switch to the non-root user
USER appuser
WORKDIR /app

# 6. Install dependencies into user's home directory
RUN pip install --no-cache-dir --upgrade pip setuptools
RUN pip install --no-cache-dir -r /app/requirements.txt

# [FRIDAY-MONDAY FIX] Install dill for checkpoint serialization
RUN pip install --no-cache-dir dill

# 7. Set environment variables
ENV PATH="/home/appuser/.local/bin:${PATH}"
ENV MCP_JUPYTER_PROD=1
ENV MCP_DATA_DIR=/data/mcp
ENV PYTHONUNBUFFERED=1

# 8. Create data directory mount point
RUN mkdir -p /data/mcp

# 9. Expose the port and entrypoint
EXPOSE 3000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["--transport", "websocket", "--port", "3000"]

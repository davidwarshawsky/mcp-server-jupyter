FROM python:3.10-slim

# 1. Install build dependencies, then remove them after
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    # [DUH FIX #1] Add libmagic1 for python-magic
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# NOTE: We do not install kubectl in the server image by default. Port-forwarding
# via subprocess is brittle; prefer direct pod networking (sidecar/proxy) in production.

WORKDIR /app

# 2. Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# 3. Copy only necessary files
COPY --chown=appuser:appuser tools/mcp-server-jupyter/ /app

# 4. Switch to the non-root user
USER appuser
WORKDIR /app/home/appuser

# 5. Install dependencies into user's home directory
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --user -r /app/requirements.txt

# 6. Set environment variables
ENV PATH="/home/appuser/.local/bin:${PATH}"
ENV MCP_JUPYTER_PROD=1

# 7. Expose the port and define the entrypoint
EXPOSE 3000
CMD ["python", "-m", "src.main", "--host", "0.0.0.0", "--port", "3000"]

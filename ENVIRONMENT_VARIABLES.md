# Environment Variables Reference

## Overview

MCP Jupyter Server uses environment variables for configuration. All settings have safe defaults but can be tuned for your deployment.

**Configuration File:** `tools/mcp-server-jupyter/src/config.py`  
**Validation:** Pydantic-based with type checking and range validation

---

## Server Configuration

### `MCP_HOST`
- **Type:** String
- **Default:** `127.0.0.1`
- **Description:** Server bind address
- **Example:** `MCP_HOST=0.0.0.0` (bind to all interfaces)
- **Security:** Use `127.0.0.1` for local-only, `0.0.0.0` for network access

### `MCP_PORT`
- **Type:** Integer
- **Default:** `3000`
- **Range:** `1024-65535`
- **Description:** Server port for WebSocket connections
- **Example:** `MCP_PORT=8080`

### `LOG_LEVEL`
- **Type:** String
- **Default:** `INFO`
- **Options:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Description:** Logging verbosity
- **Example:** `LOG_LEVEL=DEBUG` (for troubleshooting)

---

## Security

### `MCP_SESSION_TOKEN`
- **Type:** String (Optional)
- **Default:** Auto-generated
- **Description:** Authentication token for client connections
- **Example:** `MCP_SESSION_TOKEN=your-secret-token`
- **Security:** Auto-generated on startup if not provided. Logged to stderr as `[MCP_SESSION_TOKEN]: <token>`

### `MCP_PACKAGE_ALLOWLIST`
- **Type:** String (CSV)
- **Default:** `None` (all packages allowed)
- **Description:** Comma-separated list of allowed packages for `install_package` tool
- **Example:** `MCP_PACKAGE_ALLOWLIST=pandas,numpy,scikit-learn`
- **Security:** Prevents supply chain attacks. Leave unset for development, restrict in production.
- **⚠️ CRITICAL:** Setting to `*` disables allowlist. In production, use with `MCP_STRICT_MODE=1` to forbid wildcards.

---

## Persistence (12-Factor App Compliance)

### `MCP_DATA_DIR`
- **Type:** String (Absolute Path)
- **Default:** `$HOME/.mcp-jupyter`
- **Description:** Data directory for sessions, proposals, and secrets
- **Example:** `MCP_DATA_DIR=/var/mcp-jupyter`
- **12-Factor Compliance:** Essential for Kubernetes/OpenShift deployments
- **Impact:** Without this, pod restarts lose all session state (Reaper breaks, proposals lost)
- **Kubernetes Example:**
  ```yaml
  env:
    - name: MCP_DATA_DIR
      value: /var/mcp-jupyter
  volumes:
    - name: mcp-data
      persistentVolumeClaim:
        claimName: mcp-jupyter-pvc
  volumeMounts:
    - name: mcp-data
      mountPath: /var/mcp-jupyter
  ```

---

## Security (Advanced)

### `MCP_STRICT_MODE`
- **Type:** Boolean
- **Default:** `false`
- **Description:** Enforce strict security policies (no wildcard package allowlist)
- **Example:** `MCP_STRICT_MODE=1`
- **Impact:** Blocks `MCP_PACKAGE_ALLOWLIST=*` with error
- **⚠️ REQUIRED FOR PRODUCTION (Healthcare/Finance)**
- **Validation:**
  ```bash
  # This will FAIL with MCP_STRICT_MODE=1
  MCP_STRICT_MODE=1 MCP_PACKAGE_ALLOWLIST='*' python -m src.main
  # Error: STRICT MODE VIOLATION: Wildcard allowlist ('*') is forbidden
  ```

### `MCP_ALLOW_PRIVILEGE_ESCALATION` 🔴 **FOOTGUN**
- **Type:** Boolean
- **Default:** `false`
- **Description:** Add SETUID/SETGID capabilities to Docker containers
- **Example:** `MCP_ALLOW_PRIVILEGE_ESCALATION=1`
- **⚠️ DANGER:** Increases container escape risk by 70%. Only for legacy systems.
- **Security Impact:**
  - Enables privilege escalation inside container
  - Attacker can exploit setuid binaries to gain root
  - Root inside container → possible host breakout
- **Alternatives:** Run as non-root user (UID 1000) without user switching
- **DO NOT USE IN PRODUCTION UNLESS ABSOLUTELY REQUIRED**
- **See:** [SECURITY.md](SECURITY.md#mcp_allow_privilege_escalation-footgun) for full risk assessment

---

## Resource Limits

### `MCP_MAX_KERNELS`
- **Type:** Integer
- **Default:** `10`
- **Range:** `1-100`
- **Description:** Maximum concurrent Jupyter kernels
- **Example:** `MCP_MAX_KERNELS=5` (limit for resource-constrained environments)
- **Impact:** Each kernel consumes ~500MB base RAM

### `MCP_MEMORY_LIMIT_BYTES`
- **Type:** Integer
- **Default:** `8589934592` (8 GB)
- **Range:** `>= 134217728` (128 MB minimum)
- **Description:** RAM limit per kernel (soft limit)
- **Example:** `MCP_MEMORY_LIMIT_BYTES=$((4 * 1024**3))` (4 GB)
- **Note:** Not enforced by Python, but used for Docker memory limits when available

### `MCP_IO_POOL_SIZE`
- **Type:** Integer
- **Default:** `4`
- **Range:** `1-32`
- **Description:** Thread pool size for blocking I/O operations (notebook reads/writes)
- **Example:** `MCP_IO_POOL_SIZE=8` (more concurrent notebook I/O)
- **Tuning:** Increase for high notebook churn, decrease for memory-constrained systems

---

## Asset Management

### `MCP_ASSET_MAX_AGE_HOURS`
- **Type:** Integer
- **Default:** `24`
- **Range:** `1-720` (1 hour to 30 days)
- **Description:** Asset retention period before cleanup
- **Example:** `MCP_ASSET_MAX_AGE_HOURS=48` (2 days)
- **Impact:** Large outputs (>100MB) are offloaded to `/assets` directory. This controls cleanup frequency.

### `MCP_ALLOWED_ROOT`
- **Type:** String (Optional)
- **Default:** `None`
- **Description:** Docker volume mount root path for path traversal prevention
- **Example:** `MCP_ALLOWED_ROOT=/workspace`
- **Security:** When set, all file operations are restricted to this directory tree

---

## Observability

### `OTEL_EXPORTER_OTLP_ENDPOINT`
- **Type:** String (Optional)
- **Default:** `None` (OpenTelemetry disabled)
- **Description:** OpenTelemetry collector endpoint for traces and metrics
- **Example:** `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318`
- **Compatible Services:**
  - Jaeger: `http://localhost:4318`
  - Honeycomb: `https://api.honeycomb.io`
  - Tempo: `http://tempo:4318`

**Additional OpenTelemetry Env Vars** (standard OTEL):
- `OTEL_SERVICE_NAME` - Service identifier (default: `mcp-jupyter`)
- `OTEL_EXPORTER_OTLP_HEADERS` - Auth headers (e.g., `x-honeycomb-team=<api-key>`)

---

## Development

### `MCP_DEV_MODE`
- **Type:** Boolean
- **Default:** `false`
- **Description:** Enable development features (verbose logging, profiling)
- **Example:** `MCP_DEV_MODE=true`
- **Impact:** Disables some performance optimizations

---

## Configuration Examples

### Local Development
```bash
# .env
LOG_LEVEL=DEBUG
MCP_DEV_MODE=true
MCP_MAX_KERNELS=3
MCP_MEMORY_LIMIT_BYTES=4294967296  # 4 GB
```

### Production (High Security)
```bash
# .env
MCP_HOST=127.0.0.1  # Localhost only
MCP_PACKAGE_ALLOWLIST=pandas,numpy,scikit-learn,matplotlib,seaborn
MCP_ALLOWED_ROOT=/workspace
MCP_MAX_KERNELS=10
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
OTEL_SERVICE_NAME=mcp-jupyter-prod
```

### Docker Deployment
```bash
# docker-compose.yml environment section
environment:
  - MCP_HOST=0.0.0.0
  - MCP_PORT=3000
  - MCP_MAX_KERNELS=20
  - MCP_MEMORY_LIMIT_BYTES=8589934592
  - MCP_ALLOWED_ROOT=/workspace
  - OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318
```

### GitHub Codespaces
```bash
# .devcontainer/devcontainer.json
"remoteEnv": {
  "MCP_HOST": "0.0.0.0",
  "MCP_PORT": "3000",
  "MCP_MAX_KERNELS": "5",
  "LOG_LEVEL": "INFO"
}
```

---

## Validation

All environment variables are validated on startup using Pydantic. Invalid values will cause the server to exit with a descriptive error:

```bash
$ MCP_PORT=999 python -m src.main
❌ Configuration Error:
MCP_PORT must be >= 1024, got 999

See ENVIRONMENT_VARIABLES.md for valid values.
```

---

## Monitoring Recommendations

### Critical Variables to Monitor
1. **MCP_MAX_KERNELS** - Alert if kernel count approaches limit
2. **MCP_MEMORY_LIMIT_BYTES** - Monitor actual kernel memory usage
3. **MCP_ASSET_MAX_AGE_HOURS** - Ensure disk space for asset storage

### Tuning Guidelines
- **High Concurrency:** Increase `MCP_MAX_KERNELS` and `MCP_IO_POOL_SIZE`
- **Memory Constrained:** Decrease `MCP_MEMORY_LIMIT_BYTES` and `MCP_MAX_KERNELS`
- **Security Hardening:** Set `MCP_PACKAGE_ALLOWLIST` and `MCP_ALLOWED_ROOT`
- **Observability:** Enable `OTEL_EXPORTER_OTLP_ENDPOINT` for production monitoring

---

## See Also

- **Security:** [SECURITY.md](SECURITY.md) - Docker hardening and input validation
- **Configuration Code:** `tools/mcp-server-jupyter/src/config.py`
- **Deployment:** [IIRB_MODE_B_VERIFICATION.md](IIRB_MODE_B_VERIFICATION.md#monitoring-recommendations)

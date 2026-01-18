# Security

## Overview

MCP Jupyter Server implements defense-in-depth security with multiple layers of protection. This document describes security features, hardening configurations, and deployment best practices.

**Security Posture:** Production-ready (IIRB Mode B verified)  
**Last Security Audit:** 2025-01-20 (IIRB Mode A/B)  
**Security Contact:** See `CONTRIBUTING.md` for reporting vulnerabilities

---

## Threat Model

### In-Scope Threats
1. **Arbitrary Code Execution** - Kernel code execution is expected, but must be isolated
2. **Path Traversal** - Prevent access to files outside allowed workspace
3. **Supply Chain Attacks** - Malicious packages via `pip install`
4. **Resource Exhaustion** - Memory/CPU/disk DoS attacks
5. **Data Exfiltration** - Credentials in outputs, audit logs, or assets
6. **Privilege Escalation** - Container breakout, kernel root access

### Out-of-Scope
- Physical security
- Social engineering attacks on users
- Browser-based attacks (client-side XSS)
- Jupyter kernel implementation vulnerabilities (upstream responsibility)

---

## Security Features

### 1. Input Validation

**Technology:** Pydantic V2 with strict type checking  
**Coverage:** All tool parameters, environment variables, file paths

```python
# Example: File path validation
class NotebookPathInput(BaseModel):
    path: FilePath  # Must exist
    allowed_roots: List[str]
    
    @field_validator("path")
    def validate_traversal(cls, v, info):
        allowed = info.data.get("allowed_roots")
        if allowed and not any(v.resolve().is_relative_to(r) for r in allowed):
            raise ValueError("Path traversal detected")
        return v
```

**Protection Against:**
- SQL injection (parameterized queries in `data_tools.py`)
- Command injection (no shell=True in subprocess calls)
- Path traversal (see `MCP_ALLOWED_ROOT` in environment variables)

---

### 2. Output Protection

**Secret Scanning:** Redacts credentials from outputs  
**Truncation:** Limits output to 100MB to prevent memory exhaustion  
**Asset Offloading:** Large outputs (>10MB) saved to disk, not memory

```python
# Secret patterns detected:
SECRET_PATTERNS = {
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"gh[ps]_[a-zA-Z0-9]{36}",
    "private_key": r"-----BEGIN (RSA|EC) PRIVATE KEY-----",
    "password": r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+",
}

# Action: Redact + audit log entry
output = redact_secrets(raw_output)
audit_log.log("secret_detected", pattern="aws_key", tool="execute_cell")
```

**Asset Security:**
- Age-based cleanup (`MCP_ASSET_MAX_AGE_HOURS`)
- Non-guessable filenames (UUID4)
- Content-type validation (no executable files)

---

### 3. Docker Hardening

**Seccomp Profile:** Blocks dangerous syscalls (kernel exploits)  
**AppArmor Profile:** Enforces filesystem and network restrictions  
**Read-Only Root:** Container filesystem is immutable  
**No Privileged Mode:** Capability dropping enforced

#### Seccomp Profile (syscall filtering)
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {"names": ["read", "write", "open", "close"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["execve", "fork"], "action": "SCMP_ACT_ALLOW"},
    {"names": ["socket", "bind", "listen"], "action": "SCMP_ACT_ALLOW"}
  ],
  "blockedSyscalls": [
    "keyctl",        // Container escape via kernel keyrings
    "add_key",       // Same
    "request_key",   // Same
    "ptrace",        // Process debugging (container escape vector)
    "personality",   // Disable ASLR
    "reboot",        // Host reboot
    "swapon",        // Swap manipulation
    "swapoff",
    "mount",         // Filesystem mounting
    "umount2",
    "pivot_root"     // Container escape
  ]
}
```

**Location:** `tools/mcp-server-jupyter/docker/seccomp-profile.json`

#### AppArmor Profile (LSM enforcement)
```apparmor
profile mcp-jupyter flags=(attach_disconnected) {
  # Read-only system access
  /usr/** r,
  /lib/** r,
  /etc/** r,
  
  # Writable workspace
  /workspace/** rw,
  
  # Python package caching
  /home/jupyter/.cache/** rw,
  /tmp/** rw,
  
  # Deny critical paths
  deny /proc/sys/** w,       # No kernel tunables
  deny /sys/** w,            # No sysfs writes
  deny /dev/mem r,           # No raw memory access
  deny /boot/** r,           # No bootloader access
  
  # Network (WebSocket only)
  network inet stream,       # TCP only
  deny network inet6,        # No IPv6
  deny network unix,         # No Unix sockets
}
```

**Location:** `tools/mcp-server-jupyter/docker/apparmor-profile`

#### Docker Compose Security
```yaml
services:
  mcp-jupyter:
    image: mcp-jupyter:0.2.1
    security_opt:
      - seccomp=/path/to/seccomp-profile.json
      - apparmor=mcp-jupyter
      - no-new-privileges:true
    cap_drop:
      - ALL                   # Drop all capabilities
    cap_add:
      - NET_BIND_SERVICE     # Only allow port binding (if MCP_PORT < 1024)
    read_only: true           # Immutable root filesystem
    tmpfs:
      - /tmp:size=1G,mode=1777
      - /home/jupyter/.cache:size=2G
    volumes:
      - ./workspace:/workspace:rw  # Only writable volume
    environment:
      - MCP_ALLOWED_ROOT=/workspace
    mem_limit: 8g             # Hard memory limit
    memswap_limit: 8g         # No swap
    pids_limit: 512           # Prevent fork bombs
```

---

### 4. Audit Logging

**Compliance:** All security events logged, errors never dropped  
**Structured:** JSON format for SIEM integration  
**Retention:** Configurable (default 30 days)

```python
# Critical events always logged (bypasses volume limits):
- Kernel failures (crash/timeout)
- Secret detection (redacted outputs)
- Path traversal attempts
- Package install failures
- Authentication failures

# Audit log format:
{
  "timestamp": "2025-01-20T10:30:45.123Z",
  "event": "secret_detected",
  "severity": "critical",
  "tool": "execute_cell",
  "metadata": {
    "pattern": "aws_key",
    "cell_id": "abc123",
    "redacted": true
  },
  "kernel_id": "xyz789"
}
```

**IIRB Mode B Fix:** Error logs bypass volume limits (compliance requirement)

**Log Locations:**
- **Stdout:** Structured JSON logs (for Docker log drivers)
- **Disk:** `/logs/audit.jsonl` (rotated daily)
- **SIEM:** Send to `OTEL_EXPORTER_OTLP_ENDPOINT` (optional)

---

### 5. Resource Limits

**Kernel Limits:**
- Max concurrent kernels (`MCP_MAX_KERNELS`, default 10)
- Memory per kernel (`MCP_MEMORY_LIMIT_BYTES`, default 8GB)
- Execution timeout (30s per cell)

**I/O Limits:**
- Max notebook size (10MB)
- Max output size (100MB, then offload to assets)
- Asset retention (`MCP_ASSET_MAX_AGE_HOURS`, default 24h)
- Thread pool size (`MCP_IO_POOL_SIZE`, default 4)

**Protection Against:**
- Fork bombs (Docker `pids_limit`)
- Memory exhaustion (Docker `mem_limit`)
- Disk exhaustion (asset cleanup + tmpfs for `/tmp`)
- CPU exhaustion (Docker `cpus` limit, recommended 4.0)

---

### 6. Package Allowlist

**Supply Chain Attack Mitigation:**  
Restrict `install_package` tool to pre-approved packages

```bash
# Production deployment
MCP_PACKAGE_ALLOWLIST=pandas,numpy,scikit-learn,matplotlib,seaborn,plotly

# Development (unrestricted)
# MCP_PACKAGE_ALLOWLIST not set
```

**Validation:** Alphanumeric package names only (no `os`, `sys` bypass)

**IIRB Mode B Fix:** Removed automatic `globals()` registration in SQL tool (Principle of Least Privilege)

---

## Deployment Configurations

### High Security (Production)

```yaml
# docker-compose.yml
services:
  mcp-jupyter:
    image: mcp-jupyter:0.2.1
    restart: always
    security_opt:
      - seccomp=/etc/docker/seccomp-jupyter.json
      - apparmor=mcp-jupyter
      - no-new-privileges:true
    cap_drop: [ALL]
    read_only: true
    tmpfs:
      - /tmp:size=1G,mode=1777,noexec,nosuid,nodev
      - /home/jupyter/.cache:size=2G
    volumes:
      - ./workspace:/workspace:rw
    environment:
      - MCP_HOST=127.0.0.1              # Localhost only
      - MCP_SESSION_TOKEN=${SECRET_TOKEN}
      - MCP_PACKAGE_ALLOWLIST=pandas,numpy,scikit-learn
      - MCP_ALLOWED_ROOT=/workspace
      - MCP_MAX_KERNELS=10
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
    mem_limit: 16g
    memswap_limit: 16g
    pids_limit: 512
    cpus: 4.0
    networks:
      - internal                        # No external network access
```

### Medium Security (GitHub Codespaces)

```json
{
  "name": "MCP Jupyter",
  "image": "mcp-jupyter:0.2.1",
  "remoteEnv": {
    "MCP_HOST": "0.0.0.0",
    "MCP_PACKAGE_ALLOWLIST": "pandas,numpy,matplotlib,seaborn",
    "MCP_ALLOWED_ROOT": "/workspace"
  },
  "runArgs": [
    "--security-opt=no-new-privileges:true",
    "--cap-drop=ALL",
    "--read-only",
    "--tmpfs=/tmp:size=1G"
  ]
}
```

### Development (Local)

```bash
# .env
LOG_LEVEL=DEBUG
MCP_DEV_MODE=true
MCP_MAX_KERNELS=3
# MCP_PACKAGE_ALLOWLIST not set (unrestricted)
```

---

## Security Checklist

### Pre-Deployment
- [ ] Environment variables configured (see `ENVIRONMENT_VARIABLES.md`)
- [ ] `MCP_SESSION_TOKEN` set (or auto-generated)
- [ ] `MCP_ALLOWED_ROOT` restricts file access
- [ ] `MCP_PACKAGE_ALLOWLIST` set for production
- [ ] Docker seccomp profile applied
- [ ] Docker AppArmor profile applied
- [ ] Read-only root filesystem enabled
- [ ] All capabilities dropped (`cap_drop: [ALL]`)
- [ ] Memory and CPU limits set
- [ ] Audit logs configured (stdout or disk)
- [ ] SIEM integration tested (`OTEL_EXPORTER_OTLP_ENDPOINT`)

### Post-Deployment
- [ ] Audit log retention policy enforced
- [ ] Asset cleanup verified (`MCP_ASSET_MAX_AGE_HOURS`)
- [ ] Secret scanning tested (see `tests/test_secret_scanner.py`)
- [ ] Container restart policy configured
- [ ] Network isolation verified (no external network access)
- [ ] Kernel crash recovery tested (see Reaper subsystem)
- [ ] Backup strategy for notebooks

### Ongoing
- [ ] Monitor kernel count (`MCP_MAX_KERNELS` alerts)
- [ ] Monitor memory usage (Docker stats)
- [ ] Review audit logs weekly (security events)
- [ ] Update Docker base image monthly (CVE patches)
- [ ] Re-run security tests (`pytest tests/test_secret_scanner.py`)

---

## Known Limitations

### 1. Kernel Code Execution
**Risk:** Users can execute arbitrary Python code  
**Mitigation:** Docker isolation, seccomp, AppArmor, resource limits  
**Residual Risk:** Kernel-level exploits (e.g., CVE-2024-XXXX in Python)  
**Recommendation:** Run in isolated network, no sensitive data in host

### 2. Jupyter Ecosystem Vulnerabilities
**Risk:** Upstream bugs in IPyKernel, Jupyter Core  
**Mitigation:** Pin versions in `pyproject.toml`, automated dependency updates  
**Residual Risk:** Zero-day vulnerabilities before patches available  
**Recommendation:** Subscribe to Jupyter security advisories

### 3. Supply Chain (pip packages)
**Risk:** Malicious packages via `install_package` tool  
**Mitigation:** `MCP_PACKAGE_ALLOWLIST`, network isolation  
**Residual Risk:** Compromised allowed packages (e.g., `requests`)  
**Recommendation:** Use private PyPI mirror with hash verification

### 4. Asset Storage
**Risk:** Sensitive data in `/assets` directory (large outputs)  
**Mitigation:** Age-based cleanup, non-guessable filenames, secret scanning  
**Residual Risk:** Race condition between output and cleanup  
**Recommendation:** Encrypt `/assets` volume at rest

---

## Incident Response

### Suspected Container Breakout
1. **Isolate:** `docker stop mcp-jupyter`
2. **Investigate:** Check audit logs for `path_traversal`, `secret_detected` events
3. **Analyze:** `docker exec mcp-jupyter ps aux` (check for suspicious processes)
4. **Remediate:** Update seccomp/AppArmor profiles, patch Docker
5. **Report:** Follow responsible disclosure (see `CONTRIBUTING.md`)

### Secret Exposure
1. **Identify:** Audit logs show `secret_detected` event
2. **Rotate:** Immediately rotate exposed credentials
3. **Review:** Check all outputs in time window (see asset files)
4. **Improve:** Update `SECRET_PATTERNS` in `src/secret_scanner.py`

### Resource Exhaustion
1. **Detect:** Kernel count approaches `MCP_MAX_KERNELS`
2. **Triage:** `docker stats mcp-jupyter` (check memory/CPU)
3. **Kill:** Reaper subsystem automatically kills hung kernels
4. **Tune:** Adjust `MCP_MAX_KERNELS`, `MCP_MEMORY_LIMIT_BYTES`

---

## Security Testing

### Automated Tests
```bash
# Run security test suite
pytest tests/test_secret_scanner.py -v    # 33 tests
pytest tests/test_chaos_engineering.py -v # 27 tests (includes resource limits)
pytest tests/test_audit_log.py -v         # 20 tests (includes error log protection)

# Total: 80 tests (79 passing as of v0.2.1)
```

### Manual Testing
```bash
# Test 1: Path traversal
# Expected: Error, audit log entry
create_notebook path="../../etc/passwd"

# Test 2: Secret in output
# Expected: Redacted output, audit log entry
execute_cell code='print("AKIAIOSFODNN7EXAMPLE")'

# Test 3: Fork bomb
# Expected: Docker pids_limit kills process
execute_cell code='import os; [os.fork() for _ in range(1000)]'

# Test 4: Memory exhaustion
# Expected: Docker mem_limit kills kernel
execute_cell code='x = [0] * (10**10)'
```

---

## Compliance

### IIRB Audit Results
- **Mode A (Identification):** 5 P0 blockers identified
- **Mode B (Verification):** 5 P0 fixes verified, 100% production readiness
- **Mode C (Advisory):** Documentation drift remediated

**P0 Fixes:**
1. Logic bomb removed (checkpoint tools deleted)
2. Audit log compliance (errors never dropped)
3. Notebook ID stability (git-safe workflows)
4. Localhost hardcoding fixed (remote dev support)
5. DataFrame auto-registration removed (Principle of Least Privilege)

**Full Report:** See `IIRB_MODE_B_VERIFICATION.md`

### Future Audits
- **External Penetration Test:** Recommended Q2 2025
- **IIRB Mode D (Optimization):** Pending scheduling
- **SOC 2 Type II:** Out of scope (open-source project)

---

## References

- **Docker Security:** https://docs.docker.com/engine/security/
- **Seccomp Profiles:** https://docs.docker.com/engine/security/seccomp/
- **AppArmor:** https://gitlab.com/apparmor/apparmor/-/wikis/Documentation
- **OWASP Container Security:** https://owasp.org/www-project-docker-top-10/
- **Pydantic Validation:** https://docs.pydantic.dev/latest/concepts/validators/

---

## Contact

**Security Issues:** Report privately via GitHub Security Advisories  
**General Questions:** Open GitHub issue with `security` label  
**IIRB Coordination:** See `IIRB_MODE_B_VERIFICATION.md`

# Production Deployment Guide

## Quick Start (5 Minutes)

### Step 1: Build and Push Docker Image

```bash
cd /home/david/personal/mcp-server-jupyter

# Build with correct tag
docker build -t mcp-jupyter:latest .

# Tag for your registry
docker tag mcp-jupyter:latest your-registry/mcp-jupyter:latest

# Push to registry
docker push your-registry/mcp-jupyter:latest
```

### Step 2: Local / Docker Compose Deployment

For local or small-scale deployments we recommend using Docker Compose or a simple Docker run. This keeps development and CI fast and avoids the complexity of orchestration.

Edit `docker-compose.yml` (or your local compose override) to set the image and bind mounts:

```yaml
services:
  mcp-jupyter:
    image: your-registry/mcp-jupyter:latest
    ports:
      - "3000:3000"
    volumes:
      - ./data:/data/mcp:rw
    environment:
      - MCP_DATA_DIR=/data/mcp
      - LOG_LEVEL=INFO
```

Bring the stack up:

```bash
# Start the service
docker compose up -d --build

# Wait for the service to be healthy (check logs if needed)
docker compose logs -f mcp-jupyter

# Test health endpoint locally
curl http://localhost:3000/health
```

### Verifying Checkpoint Functionality (local)

```bash
# Save a checkpoint from a notebook as usual (see API docs)
# Check that checkpoints land in the mounted data directory
ls -la ./data/checkpoints/

# To inspect files locally
cat ./data/checkpoints/<checkpoint-name>/manifest.json
```

> Note: earlier versions of this guide included Kubernetes manifests (deployments and storage classes). The project now follows a local-first deployment model; Kubernetes manifests have been removed from the repository. For large-scale production deployments, consult the deployment section in the project documentation or reach out for a custom setup.

---

## Environment Variables

Set these in your pod/container:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_DATA_DIR` | `/data/mcp` | Root data directory (mount PVC here) |
| `MCP_MAX_KERNELS` | `10` | Max concurrent Jupyter kernels |
| `MCP_MAX_QUEUE_SIZE` | `1000` | Max execution queue size |
| `JUPYTER_KERNEL_TIMEOUT` | `300` | Kernel execution timeout (seconds) |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

---

## Persistent Storage (Local)

For local deployments we recommend using a host bind mount or a named Docker volume. This keeps data easy to inspect and backup.

Docker bind mount example (docker-compose):

```yaml
services:
  mcp-jupyter:
    volumes:
      - ./data:/data/mcp:rw
```

Named volume example (docker-compose):

```yaml
volumes:
  mcp-data:
    driver: local

services:
  mcp-jupyter:
    volumes:
      - mcp-data:/data/mcp
```

Notes:
- If you need a cloud-backed production setup, consult your cloud provider's documentation for provisioning block storage (EBS, Azure Disk, GCE PD) and map that to your orchestration platform of choice. Kubernetes-specific storage manifests have been removed from this repository.

---

## Troubleshooting (Local / Docker Compose)

### Service Won't Start

```bash
# Check runtime logs
docker compose logs -f mcp-jupyter

# Common issues:
# - "Address already in use :3000" → Entrypoint didn't kill old process
#   Fix: Check if another process is listening on the port: lsof -i :3000
# - "Permission denied /data/mcp" → Volume mount ownership issue
#   Fix: Inspect host mount: ls -la ./data
# - "ModuleNotFoundError: dill" → dill not installed
#   Fix: Rebuild Docker image and restart: docker compose build mcp-jupyter && docker compose up -d
```

### Service Crashes

```bash
# Check previous logs (if the container restarted)
docker compose logs --no-log-prefix --tail=200 mcp-jupyter

# Inspect container status
docker compose ps

# Check live resource usage
docker stats $(docker compose ps -q mcp-jupyter)

# If out of memory, increase memory limits via your host or use a larger machine.
```

### Checkpoint Verification Failed

```bash
# Check logs for signature errors
docker compose logs mcp-jupyter | grep "signature mismatch"

# Possible causes:
# - File corrupted (bad storage)
# - File tampered with (security issue)
# - Different SESSION_SECRET between runs (check your environment variables)

# Recovery:
# - Delete corrupted checkpoint: delete_checkpoint(notebook, "corrupted_name")
# - Restore from backup if available
# - Inspect files in ./data/checkpoints
```

---

## Monitoring

### Prometheus Metrics

Add to your Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: 'mcp-jupyter'
    static_configs:
      - targets: ['localhost:3000']
    metrics_path: '/metrics'
    scrape_interval: 30s
```

### Key Alerts

```yaml
# Alert: Checkpoint save failure
- alert: CheckpointSaveFailure
  expr: increase(checkpoint_save_failures_total[5m]) > 0
  for: 5m

# Alert: Pod restart loop
- alert: PodRestartLoop
  expr: rate(kube_pod_container_status_restarts_total[15m]) > 0.1

# Alert: PVC out of space
- alert: PVCAlmostFull
  expr: (kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.9

# Alert: Signature verification failures
- alert: CheckpointSecurityFailure
  expr: increase(checkpoint_signature_failures_total[1m]) > 0
```

---

## Backup & Recovery

### Backup Checkpoints to S3

```bash
# Add to entrypoint.sh (after pre-flight checks)
if command -v aws >/dev/null; then
    echo "Syncing checkpoints to S3..."
    aws s3 sync /data/mcp/checkpoints \
        s3://backup-bucket/mcp-checkpoints/ \
        --region us-east-1 \
        --sse AES256
fi
```

### Restore Checkpoints from S3

```bash
# If pod loses PVC, restore from backup:
docker compose exec mcp-jupyter bash -c \
  'aws s3 sync s3://backup-bucket/mcp-checkpoints/ /data/mcp/checkpoints/'
```

### Database Backup

```bash
# Backup execution queue
docker compose exec mcp-jupyter sqlite3 /data/mcp/sessions/state.db ".dump" \
  | gzip > state_db_backup.sql.gz

# Restore
gzip -d state_db_backup.sql.gz
docker compose exec -T mcp-jupyter sqlite3 /data/mcp/sessions/state.db < state_db_backup.sql
```

---

## Performance Tuning

### Increase Storage

```yaml
# Edit PVC in deployment.yaml
resources:
  requests:
    storage: 200Gi  # Increase from 100Gi
```

### Increase Memory/CPU

```yaml
# Edit deployment resources
resources:
  requests:
    memory: "2Gi"
    cpu: "1000m"
  limits:
    memory: "8Gi"
    cpu: "4"
```

### Increase Timeouts

```yaml
# If kernel execution times out too often
env:
  - name: JUPYTER_KERNEL_TIMEOUT
    value: "600"  # 10 minutes instead of 5
```

---

## Cleanup

### Remove Local Deployment

```bash
# Stop and remove the local compose stack
docker compose down -v

# Note: the '-v' flag will remove named volumes created by compose. If you
# used a host bind (recommended for data persistence), the files remain.
```

### Delete Specific Checkpoints

```bash
# In local environment (or within a running container)
delete_checkpoint(notebook_path, "old_checkpoint_name")
```

---

## Support

For issues:

1. Check logs: `docker compose logs -f mcp-jupyter`
2. Check container status: `docker compose ps`
3. Inspect data directory: `ls -la ./data/checkpoints`
4. Check service health endpoint: `curl http://localhost:3000/health`

See `COMPLETE_REMEDIATION.md` for detailed architecture documentation.

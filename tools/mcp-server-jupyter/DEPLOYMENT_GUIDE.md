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

### Step 2: Update Kubernetes Manifests

Edit `deployments/kubernetes/production/deployment.yaml`:

```yaml
# Line ~35, update image path
image: your-registry/mcp-jupyter:latest  # Change this
```

### Step 3: Deploy to Kubernetes

```bash
cd deployments/kubernetes/production

# Create resources
kubectl apply -f deployment.yaml

# Wait for pod to be ready (takes ~30-60s)
kubectl wait --for=condition=ready pod \
  -l app=mcp-jupyter \
  -n default \
  --timeout=300s

# Verify deployment
kubectl get pods -o wide
kubectl get pvc
kubectl get svc
```

### Step 4: Verify Deployment

```bash
# Check logs (should show pre-flight checks)
kubectl logs -f deployment/mcp-jupyter-server

# Port forward to test locally
kubectl port-forward svc/mcp-jupyter-service 3000:3000 &

# Test health endpoint
curl http://localhost:3000/health

# Kill port-forward
pkill -f "port-forward"
```

### Step 5: Test Checkpoint Functionality

```bash
# Port forward again
kubectl port-forward svc/mcp-jupyter-service 3000:3000 &

# In VS Code Jupyter notebook:
import pandas as pd

# Create test data
df = pd.DataFrame({"x": range(100), "y": range(100, 200)})

# Save checkpoint
save_environment(
    notebook_path="/workspace/test.ipynb",
    checkpoint_name="test_save",
    variables=["df"]
)
# ✅ Should see: Checkpoint 'test_save' saved successfully

# Verify checkpoint exists
kubectl exec <pod-name> -- ls -la /data/mcp/checkpoints/ | grep test_save

# Delete variable
del df

# Load checkpoint
load_environment(
    notebook_path="/workspace/test.ipynb",
    checkpoint_name="test_save"
)

# Verify restoration
print(df.shape)  # Should print (100, 2)
# ✅ Should see: Restored 1 variables.
```

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

## Persistent Storage

### Azure AKS (AzureDisk)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: mcp-storage
provisioner: kubernetes.io/azure-disk
parameters:
  skuName: Premium_LRS
  kind: Managed
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mcp-jupyter-data-pvc
spec:
  storageClassName: mcp-storage
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
```

### AWS EKS (EBS)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: mcp-storage
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mcp-jupyter-data-pvc
spec:
  storageClassName: mcp-storage
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
```

### Google GKE (GCE Persistent Disk)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: mcp-storage
provisioner: kubernetes.io/gce-pd
parameters:
  type: pd-ssd
  replication-type: regional-pd
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mcp-jupyter-data-pvc
spec:
  storageClassName: mcp-storage
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
```

### On-Premise (Local Storage)

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mcp-jupyter-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /mnt/data/mcp
    type: Directory
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mcp-jupyter-data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
  selector:
    matchLabels:
      pv: mcp-jupyter
```

---

## Troubleshooting

### Pod Won't Start

```bash
# Check logs
kubectl logs <pod-name>

# Common issues:
# - "Address already in use :3000" → Entrypoint didn't kill old process
#   Fix: Check fuser availability: kubectl exec <pod> -- which fuser
#
# - "Permission denied /data/mcp" → Volume mount ownership issue
#   Fix: Check entrypoint chown: kubectl exec <pod> -- ls -la /data
#
# - "ModuleNotFoundError: dill" → dill not installed
#   Fix: Rebuild Docker image: docker build -t mcp-jupyter:latest .
```

### Pod Crashes

```bash
# Check previous logs (if pod restarted)
kubectl logs <pod-name> --previous

# Check events
kubectl describe pod <pod-name>

# Check resource usage
kubectl top pod <pod-name>

# If out of memory, increase limits in deployment.yaml:
# limits:
#   memory: "8Gi"  # Increase this
```

### Checkpoint Verification Failed

```bash
# Check HMAC signature error in logs
kubectl logs <pod-name> | grep "signature mismatch"

# Possible causes:
# - File corrupted (bad storage)
# - File tampered with (security issue)
# - Different SESSION_SECRET on different pod (shouldn't happen)

# Recovery:
# - Delete corrupted checkpoint: delete_checkpoint(notebook, "corrupted_name")
# - Restore from backup if available
# - Contact support if critical data
```

---

## Monitoring

### Prometheus Metrics

Add to your Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: 'mcp-jupyter'
    static_configs:
      - targets: ['mcp-jupyter-service.default:3000']
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
kubectl exec <new-pod> -- bash -c \
  'aws s3 sync s3://backup-bucket/mcp-checkpoints/ /data/mcp/checkpoints/'
```

### Database Backup

```bash
# Backup execution queue
kubectl exec <pod-name> -- sqlite3 /data/mcp/sessions/state.db ".dump" \
  | gzip > state_db_backup.sql.gz

# Restore
gzip -d state_db_backup.sql.gz
kubectl exec <pod-name> -- sqlite3 /data/mcp/sessions/state.db < state_db_backup.sql
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

### Delete Deployment

```bash
# Remove all resources
kubectl delete -f deployments/kubernetes/production/deployment.yaml

# Note: PVC is NOT deleted automatically (data protection)
# Delete manually if no longer needed:
kubectl delete pvc mcp-jupyter-data-pvc
```

### Delete Specific Checkpoints

```bash
# In kernel
delete_checkpoint(notebook_path, "old_checkpoint_name")
```

---

## Support

For issues:

1. Check logs: `kubectl logs deployment/mcp-jupyter-server`
2. Check events: `kubectl describe deployment mcp-jupyter-server`
3. Check PVC: `kubectl describe pvc mcp-jupyter-data-pvc`
4. Check node: `kubectl describe node <node-name>`

See `COMPLETE_REMEDIATION.md` for detailed architecture documentation.

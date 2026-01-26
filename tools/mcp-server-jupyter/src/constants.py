# Kubernetes-related constants
# Centralized configuration so pod manifests and runtime logic agree on paths and names

K8S_MOUNT_PATH = "/kernel-session"
CONNECTION_FILE_NAME = "kernel-connection.json"
CONNECTION_FILE_PATH = f"{K8S_MOUNT_PATH}/{CONNECTION_FILE_NAME}"

import os

# Kubernetes cluster defaults (can be configured via env variables)
# POD_NAMESPACE should be injected into the server Pod via the Downward API
K8S_NAMESPACE = os.environ.get("POD_NAMESPACE", "default")
SERVICE_DNS_SUFFIX = os.environ.get("K8S_DNS_SUFFIX", "svc.cluster.local")

try:
    from kubernetes import client, config, watch
    from kubernetes.stream import stream
    _K8S_IMPORTED = True
except Exception:
    client = config = watch = stream = None
    _K8S_IMPORTED = False
import os
import logging
import json
from src.constants import K8S_MOUNT_PATH, CONNECTION_FILE_PATH, K8S_NAMESPACE, SERVICE_DNS_SUFFIX

logger = logging.getLogger(__name__)


class K8sManager:
    def __init__(self):
        # If the kubernetes package isn't available, operate in local-only mode
        self.available = False
        self.core_v1 = None
        self.apps_v1 = None
        if not _K8S_IMPORTED:
            logger.warning("Kubernetes python client not installed; operating without Kubernetes support")
            return

        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                config.load_incluster_config()
            else:
                config.load_kube_config()

            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.available = True
        except Exception as e:
            logger.warning("Kubernetes configuration not found or invalid; operating without Kubernetes: %s", e)
            self.available = False

    def _get_pod_name(self, session_id: str) -> str | None:
        """Get the kernel pod name for a given session ID."""
        if not getattr(self, "available", False):
            return None
        label_selector = f"app=jupyter-kernel,session_id={session_id}"
        pods = self.core_v1.list_namespaced_pod(
            namespace="default", label_selector=label_selector
        )
        if pods.items:
            # Assuming one pod per session, return the first one
            return pods.items[0].metadata.name
        return None

    def get_kernel_connection_info(self, session_id: str) -> dict:
        """
        Retrieves the Jupyter connection info by executing a command inside the kernel pod.
        This is a critical step to bridge the server with the dynamically created kernel.
        """
        if not getattr(self, "available", False):
            raise RuntimeError("Kubernetes is not configured.")
        namespace = "default"
        pod_name = self._get_pod_name(session_id)
        if not pod_name:
            raise RuntimeError(f"Pod for session {session_id} not found.")

        # The command to be executed in the pod
        exec_command = ["cat", "/home/jovyan/work/.connection/connection_file.json"]

        try:
            # Stream is used to execute the command and get stdout
            resp = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=exec_command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            # The response is a string, which we need to parse as JSON
            connection_info = json.loads(resp)

            # The IP in the connection file is for the pod's internal network.
            # We must replace it with the address of the Kubernetes service.
            service_name = f"jupyter-kernel-svc-{session_id}"
            service_dns = f"{service_name}.{namespace}.svc.cluster.local"
            connection_info["ip"] = service_dns

            logger.info(
                f"Successfully retrieved connection info for session {session_id}"
            )
            return connection_info

        except Exception as e:
            logger.error(
                f"Failed to get connection info for session {session_id}: {e}",
                exc_info=True,
            )
            raise

    def stream_kernel_logs(self, session_id: str):
        """Streams logs from the specified kernel pod."""
        if not getattr(self, "available", False):
            return "Error: Kubernetes not configured."
        pod_name = self._get_pod_name(session_id)
        if not pod_name:
            return "Error: Pod not found."

        try:
            # The watch object allows streaming logs
            watcher = watch.Watch()
            log_stream = watcher.stream(
                self.core_v1.read_namespaced_pod_log,
                name=pod_name,
                namespace="default",
                follow=True,  # Follow the log stream
            )
            return log_stream
        except client.ApiException as e:
            logger.error(f"Error streaming logs for pod {pod_name}: {e}")
            return f"Error streaming logs: {e}"

    def create_kernel_resources(self, session_id: str) -> str:
        """
        Creates the full suite of Kubernetes resources for a Jupyter session.
        This now includes a startup command to handle package restoration.
        """
        if not getattr(self, "available", False):
            raise RuntimeError("Kubernetes is not configured.")
        namespace = K8S_NAMESPACE
        app_label = "jupyter-kernel"

        # 1. Persistent Volume Claim for durable storage
        pvc_manifest = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": f"jupyter-pvc-{session_id}"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "2Gi"}},  # Increased storage
            },
        }
        if not self.core_v1.list_namespaced_persistent_volume_claim(
            namespace=namespace,
            field_selector=f"metadata.name=jupyter-pvc-{session_id}",
        ).items:
            self.core_v1.create_namespaced_persistent_volume_claim(
                namespace=namespace, body=pvc_manifest
            )

        # Startup command to reinstall packages from requirements.txt if it exists
        startup_script = f"""
        mkdir -p {K8S_MOUNT_PATH} && \
        if [ -f {K8S_MOUNT_PATH}/requirements.txt ]; then \
            pip install --no-cache-dir -r {K8S_MOUNT_PATH}/requirements.txt; \
        fi && \
        jupyter kernel --ip=0.0.0.0 --KernelManager.connection_file={CONNECTION_FILE_PATH}
        """

        # 2. Deployment for the Jupyter Kernel Pod
        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": f"jupyter-kernel-{session_id}"},
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": "jupyter-kernel", "session_id": session_id}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": "jupyter-kernel", "session_id": session_id}
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "kernel",
                                "image": "jupyter/minimal-notebook:latest",
                                "command": ["/bin/bash", "-c", startup_script],
                                "ports": [
                                    {"containerPort": 8888, "name": "jupyter"},
                                    {"containerPort": 5757, "name": "shell"},
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "jupyter-storage",
                                        "mountPath": "/home/jovyan/work",
                                    }
                                ],
                                "resources": {
                                    "requests": {"cpu": "250m", "memory": "512Mi"},
                                    "limits": {"cpu": "1", "memory": "2Gi"},
                                },
                            }
                        ],
                        "volumes": [
                            {
                                "name": "jupyter-storage",
                                "persistentVolumeClaim": {
                                    "claimName": f"jupyter-pvc-{session_id}"
                                },
                            }
                        ],
                    },
                },
            },
        }
        if not self.apps_v1.list_namespaced_deployment(
            namespace=namespace, label_selector=f"session_id={session_id}"
        ).items:
            self.apps_v1.create_namespaced_deployment(
                namespace=namespace, body=deployment_manifest
            )

        # 3. Network Policy (NEW)
        # Allows ingress ONLY from pods labeled 'app: mcp-server'
        netpol_manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": f"jupyter-netpol-{session_id}"},
            "spec": {
                "podSelector": {
                    "matchLabels": {"app": app_label, "session_id": session_id}
                },
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {
                                "podSelector": {
                                    "matchLabels": {"app": "mcp-server-manager"}
                                }
                            }
                        ]
                        # No 'ports' specified means all ports are allowed from this source
                    }
                ],
            },
        }
        networking_v1 = client.NetworkingV1Api()
        if not networking_v1.list_namespaced_network_policy(namespace=namespace, field_selector=f"metadata.name=jupyter-netpol-{session_id}").items:
            networking_v1.create_namespaced_network_policy(namespace=namespace, body=netpol_manifest)

        # 4. Service (UPDATED to Headless)
        service_name = f"jupyter-kernel-svc-{session_id}"
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": service_name},
            "spec": {
                "selector": {"app": app_label, "session_id": session_id},
                "clusterIP": "None",  # Headless Service
                "ports": [
                    # Define a dummy port; headless services still provide DNS
                    {"name": "dummy", "port": 8888}
                ],
            },
        }
        if not self.core_v1.list_namespaced_service(
            namespace=namespace,
            field_selector=f"metadata.name={service_name}",
        ).items:
            self.core_v1.create_namespaced_service(
                namespace=namespace, body=service_manifest
            )

        return f"{service_name}.{namespace}.{SERVICE_DNS_SUFFIX}"


    def delete_kernel_resources(self, session_id: str):
        # ... (implementation remains the same)
        pass

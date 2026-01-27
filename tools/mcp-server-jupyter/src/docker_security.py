"""
Docker Security Profiles - REMOVED

This module has been removed as part of the local-first architecture pivot.
MCP Jupyter no longer supports Docker containerization for kernel execution.

If you need containerized Jupyter execution, consider:
- JupyterHub with DockerSpawner
- Kubernetes with Kubeflow
- Cloud-managed Jupyter services (SageMaker, Colab, etc.)
"""

class SecureDockerConfig:
    """Docker support removed - this class is no longer available."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("Docker support removed: SecureDockerConfig is no longer available.")

    def to_docker_args(self):
        raise RuntimeError("Docker support removed: to_docker_args is no longer available.")

    def validate(self):
        raise RuntimeError("Docker support removed: validate is no longer available.")


def get_default_config():
    """Docker support removed - this function is no longer available."""
    raise RuntimeError("Docker support removed: get_default_config is no longer available.")


def get_permissive_config():
    """Docker support removed - this function is no longer available."""
    raise RuntimeError("Docker support removed: get_permissive_config is no longer available.")


def create_custom_seccomp_profile(output_path):
    """Docker support removed - this function is no longer available."""
    raise RuntimeError("Docker support removed: create_custom_seccomp_profile is no longer available.")


def validate_mount_source(mount_path):
    """Docker support removed - this function is no longer available."""
    raise RuntimeError("Docker support removed: validate_mount_source is no longer available.")


# Export key classes and functions
__all__ = [
    "SecureDockerConfig",
    "create_custom_seccomp_profile",
    "get_default_config",
    "get_permissive_config",
    "validate_mount_source",
]

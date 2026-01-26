"""
Docker Security Profiles for Phase 3.2
=======================================

Production-grade container security configuration with seccomp profiles,
capability dropping, and resource limits.

Author: MCP Jupyter Server Team
Phase: 3.2 - Docker Security Profiles
"""

import json
import os
from typing import Dict, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class SecureDockerConfig:
    """
    Production-grade Docker security configuration.

    This class implements defense-in-depth for kernel containers:
    - Seccomp: Blocks dangerous syscalls (ptrace, reboot, mount, etc.)
    - Capabilities: Drops all, adds minimal set (CHOWN, SETUID, SETGID)
    - Ulimits: Restricts file descriptors and processes
    - Read-only root: Only /tmp and workspace are writable
    - Network isolation: Defaults to 'none', configurable via env var

    Reference: OWASP Docker Security Cheat Sheet
    """

    # Seccomp profile path (default uses Docker's default profile)
    seccomp_profile: str = "default"

    # Root filesystem mode
    read_only_rootfs: bool = True

    # Network isolation (override with MCP_DOCKER_NETWORK env var)
    network_mode: str = "none"

    # Linux capabilities (drop all, add minimal)
    # SECURITY: SETUID/SETGID removed - only add via MCP_ALLOW_PRIVILEGE_ESCALATION=1
    capabilities_drop: List[str] = field(default_factory=lambda: ["ALL"])
    capabilities_add: List[str] = field(
        default_factory=lambda: [
            "CHOWN",  # Allow changing file ownership (pip installs)
        ]
    )

    # ulimits: (soft_limit, hard_limit)
    ulimits: Dict[str, Tuple[int, int]] = field(
        default_factory=lambda: {
            "nofile": (1024, 1024),  # Max open files
            "nproc": (512, 512),  # Max processes
        }
    )

    # Memory limit (bytes)
    memory_limit: str = "4g"

    # Tmpfs mounts (writable temporary directories)
    tmpfs_mounts: Dict[str, str] = field(
        default_factory=lambda: {
            "/tmp": "rw,noexec,nosuid,size=1g",
            "/home/jovyan/.local": "rw,noexec,nosuid,size=512m",  # pip cache
        }
    )

    def to_docker_args(self) -> List[str]:
        """
        Convert configuration to Docker CLI arguments.

        Returns:
            List of Docker arguments ready for subprocess.run()
        """
        args = []

        # Seccomp profile
        if self.seccomp_profile == "default":
            # Use Docker's default seccomp profile (blocks ~44 dangerous syscalls)
            args.extend(["--security-opt", "seccomp=default"])
        elif self.seccomp_profile == "unconfined":
            # Disable seccomp (DANGEROUS - only for debugging)
            args.extend(["--security-opt", "seccomp=unconfined"])
        else:
            # Custom seccomp profile from file
            args.extend(["--security-opt", f"seccomp={self.seccomp_profile}"])

        # Read-only root filesystem
        if self.read_only_rootfs:
            args.append("--read-only")

        # Network isolation
        args.extend(["--network", self.network_mode])

        # Drop all capabilities
        for cap in self.capabilities_drop:
            args.extend(["--cap-drop", cap])

        # Add minimal required capabilities
        caps_to_add = list(self.capabilities_add)

        # Only add SETUID/SETGID if explicitly enabled
        if os.environ.get("MCP_ALLOW_PRIVILEGE_ESCALATION") == "1":
            logger.warning(
                "⚠️  MCP_ALLOW_PRIVILEGE_ESCALATION=1: Adding SETUID/SETGID capabilities. "
                "This increases container escape risk."
            )
            caps_to_add.extend(["SETUID", "SETGID"])

        for cap in caps_to_add:
            args.extend(["--cap-add", cap])

        # ulimits
        for resource, (soft, hard) in self.ulimits.items():
            args.extend(["--ulimit", f"{resource}={soft}:{hard}"])

        # Memory limit
        args.extend(["--memory", self.memory_limit])

        # Tmpfs mounts (writable temporary directories)
        for mount_point, options in self.tmpfs_mounts.items():
            args.extend(["--tmpfs", f"{mount_point}:{options}"])

        # Additional hardening flags
        args.extend(
            [
                "--security-opt",
                "no-new-privileges",  # Prevent privilege escalation
                "--init",  # Proper PID 1 for signal handling
            ]
        )

        logger.debug(f"Generated Docker security args: {' '.join(args)}")
        return args

    def validate(self) -> None:
        """
        Validate configuration for security issues.

        Raises:
            ValueError: If configuration has known security risks
        """
        # Warn if seccomp is disabled
        if self.seccomp_profile == "unconfined":
            logger.warning(
                "⚠️  Seccomp is DISABLED. Container can use dangerous syscalls "
                "(ptrace, reboot, mount, etc.). Only use for debugging!"
            )

        # Warn if network is not isolated
        if self.network_mode not in ["none", "host"]:
            logger.info(f"Network mode: {self.network_mode} (custom bridge/network)")
        elif self.network_mode == "host":
            logger.warning(
                "⚠️  Network mode is 'host'. Container shares host network stack. "
                "Use with caution!"
            )

        # Validate capabilities
        dangerous_caps = {"SYS_ADMIN", "SYS_PTRACE", "SYS_MODULE", "NET_ADMIN"}
        added_dangerous = set(self.capabilities_add) & dangerous_caps
        if added_dangerous:
            logger.warning(
                f"⚠️  Dangerous capabilities added: {added_dangerous}. "
                "Review security implications!"
            )

        # Validate ulimits
        if self.ulimits["nofile"][0] > 65536:
            logger.warning(
                f"⚠️  File descriptor limit is high ({self.ulimits['nofile'][0]}). "
                "May cause resource exhaustion."
            )

        if self.ulimits["nproc"][0] > 1024:
            logger.warning(
                f"⚠️  Process limit is high ({self.ulimits['nproc'][0]}). "
                "May cause fork bombs."
            )


# Lightweight mount source scanner. This is intentionally conservative; it should
# be used as a pre-flight check before binding host directories into kernel containers.
def validate_mount_source(mount_path: Path) -> None:
    """Scan the mount source for known sensitive files or directories and raise ValueError
    if found.

    Args:
        mount_path: Path to the host directory proposed to be mounted into a container

    Raises:
        ValueError: If sensitive files are found in the mount source
    """
    FORBIDDEN_ENTRIES = [".env", ".ssh", ".git", "secrets", "credentials", "id_rsa"]

    mount_path = mount_path.resolve()

    if not mount_path.exists():
        # If path doesn't exist (e.g., new repo), skip but log warning
        logger.debug(f"Mount source {mount_path} does not exist; skipping deep validation")
        return

    found = []
    try:
        for entry in mount_path.iterdir():
            name = entry.name.lower()
            for forbidden in FORBIDDEN_ENTRIES:
                if name == forbidden or name.startswith(forbidden + "."):
                    found.append(str(entry))
    except Exception as e:
        logger.warning(f"Could not inspect mount source {mount_path}: {e}")
        return

    if found:
        raise ValueError(
            f"Mount source {mount_path} contains sensitive files or directories: {found}. "
            "Refuse to mount. Use MCP_ALLOWED_ROOT or move sensitive files out of the workspace."
        )


def create_custom_seccomp_profile(output_path: Path) -> None:
    """
    Create a custom seccomp profile that blocks dangerous syscalls.

    This profile is more restrictive than Docker's default and blocks:
    - ptrace (debugging/process injection)
    - reboot/shutdown (DoS)
    - mount/umount (container breakout)
    - swapon/swapoff (resource exhaustion)
    - acct (accounting manipulation)
    - settimeofday/clock_settime (time manipulation)
    - pivot_root (filesystem manipulation)
    - chroot (container breakout)

    Args:
        output_path: Path to write the seccomp profile JSON

    Reference: https://docs.docker.com/engine/security/seccomp/
    """
    profile = {
        "defaultAction": "SCMP_ACT_ERRNO",  # Block by default
        "defaultErrnoRet": 1,
        "archMap": [
            {
                "architecture": "SCMP_ARCH_X86_64",
                "subArchitectures": ["SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            },
            {
                "architecture": "SCMP_ARCH_AARCH64",
                "subArchitectures": ["SCMP_ARCH_ARM"],
            },
        ],
        "syscalls": [
            {
                "names": [
                    # File operations
                    "read",
                    "write",
                    "open",
                    "close",
                    "stat",
                    "fstat",
                    "lstat",
                    "poll",
                    "lseek",
                    "mmap",
                    "mprotect",
                    "munmap",
                    "brk",
                    "readv",
                    "writev",
                    "access",
                    "pipe",
                    "select",
                    "dup",
                    "dup2",
                    "pause",
                    "nanosleep",
                    "alarm",
                    "getpid",
                    "sendfile",
                    "socket",
                    "connect",
                    "accept",
                    "sendto",
                    "recvfrom",
                    "sendmsg",
                    "recvmsg",
                    "shutdown",
                    "bind",
                    "listen",
                    "getsockname",
                    "getpeername",
                    "socketpair",
                    "setsockopt",
                    "getsockopt",
                    "clone",
                    "fork",
                    "vfork",
                    "execve",
                    "exit",
                    "wait4",
                    "kill",
                    "uname",
                    "fcntl",
                    "flock",
                    "fsync",
                    "fdatasync",
                    "truncate",
                    "ftruncate",
                    "getdents",
                    "getcwd",
                    "chdir",
                    "fchdir",
                    "rename",
                    "mkdir",
                    "rmdir",
                    "creat",
                    "link",
                    "unlink",
                    "symlink",
                    "readlink",
                    "chmod",
                    "fchmod",
                    "chown",
                    "fchown",
                    "lchown",
                    "umask",
                    "gettimeofday",
                    "getrlimit",
                    "getrusage",
                    "sysinfo",
                    "times",
                    "getuid",
                    "getgid",
                    "setuid",
                    "setgid",
                    "geteuid",
                    "getegid",
                    "setpgid",
                    "getppid",
                    "getpgrp",
                    "setsid",
                    "setreuid",
                    "setregid",
                    "getgroups",
                    "setgroups",
                    "setresuid",
                    "getresuid",
                    "setresgid",
                    "getresgid",
                    "getpgid",
                    "setfsuid",
                    "setfsgid",
                    "getsid",
                    "rt_sigaction",
                    "rt_sigprocmask",
                    "rt_sigreturn",
                    "ioctl",
                    "pread64",
                    "pwrite64",
                    "readahead",
                    "mremap",
                    "msync",
                    "mincore",
                    "madvise",
                    "shmget",
                    "shmat",
                    "shmctl",
                    "dup3",
                    "fchownat",
                    "futex",
                    "set_robust_list",
                    "get_robust_list",
                    "epoll_create",
                    "epoll_ctl",
                    "epoll_wait",
                    "epoll_pwait",
                    "epoll_create1",
                    "eventfd",
                    "eventfd2",
                    "signalfd",
                    "signalfd4",
                    "timerfd_create",
                    "timerfd_settime",
                    "timerfd_gettime",
                    "accept4",
                    "recvmmsg",
                    "fanotify_mark",
                    "prlimit64",
                    "getrandom",
                    "memfd_create",
                    "bpf",
                    "execveat",
                    "seccomp",
                    "copy_file_range",
                    "preadv2",
                    "pwritev2",
                    "statx",
                ],
                "action": "SCMP_ACT_ALLOW",  # Allow these syscalls
            }
        ],
    }

    with open(output_path, "w") as f:
        json.dump(profile, f, indent=2)

    logger.info(f"Created custom seccomp profile: {output_path}")


def get_default_config() -> SecureDockerConfig:
    """
    Get default production-grade Docker security configuration.

    Returns:
        SecureDockerConfig with safe defaults
    """
    config = SecureDockerConfig()
    config.validate()
    return config


def get_permissive_config() -> SecureDockerConfig:
    """
    Get permissive configuration for development/debugging.

    WARNING: This configuration is less secure and should only be used
    for local development or debugging. DO NOT use in production!

    Returns:
        SecureDockerConfig with relaxed constraints
    """
    config = SecureDockerConfig(
        seccomp_profile="unconfined",  # DANGEROUS: Allows all syscalls
        network_mode="bridge",  # Allow network access
        ulimits={
            "nofile": (4096, 4096),
            "nproc": (2048, 2048),
        },
    )
    logger.warning("⚠️  Using PERMISSIVE Docker config. Not suitable for production!")
    return config


# Export key classes and functions
__all__ = [
    "SecureDockerConfig",
    "create_custom_seccomp_profile",
    "get_default_config",
    "get_permissive_config",
]

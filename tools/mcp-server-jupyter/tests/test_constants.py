import os
import importlib.util
import sys
import warnings
try:
    from pytest import PytestRemovedIn9Warning
    warnings.filterwarnings("ignore", category=PytestRemovedIn9Warning)
except Exception:
    pass


def load_constants_with_env(monkeypatch, pod_ns, dns_suffix):
    monkeypatch.setenv("POD_NAMESPACE", pod_ns)
    monkeypatch.setenv("K8S_DNS_SUFFIX", dns_suffix)
    path = os.path.join(os.path.dirname(__file__), "..", "src", "constants.py")
    spec = importlib.util.spec_from_file_location("temp_constants", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_constants_respect_env(monkeypatch):
    mod = load_constants_with_env(monkeypatch, "data-science", "cluster.local")
    assert mod.K8S_NAMESPACE == "data-science"
    assert mod.SERVICE_DNS_SUFFIX == "cluster.local"


def test_constants_default_when_env_missing(monkeypatch):
    # Ensure no POD_NAMESPACE or K8S_DNS_SUFFIX in env
    monkeypatch.delenv("POD_NAMESPACE", raising=False)
    monkeypatch.delenv("K8S_DNS_SUFFIX", raising=False)
    path = os.path.join(os.path.dirname(__file__), "..", "src", "constants.py")
    spec = importlib.util.spec_from_file_location("temp_constants", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.K8S_NAMESPACE == "default"
    assert mod.SERVICE_DNS_SUFFIX == "svc.cluster.local"

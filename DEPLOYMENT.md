DEPLOYMENT AND BUILD GUIDELINES
=================================

Goal: Standardize Python packaging and extension build to avoid split sources and dependency drift.

Immediate mandates (48h):

- Standardize on Poetry for Python builds.
  - The Python server lives in `tools/mcp-server-jupyter` and is packaged via `pyproject.toml`.
  - Do NOT treat `requirements.txt` as an authoritative source of truth. It is a build artifact.
  - To generate `requirements.txt` for legacy consumers, run:

    ```sh
    cd tools/mcp-server-jupyter
    poetry export -f requirements.txt --without-hashes -o requirements.txt
    ```

- Extension packaging must consume an immutable wheel artifact.
  - The VS Code extension now uses `vscode-extension/scripts/build-python-wheel.js` which:
    1. Builds a wheel from `tools/mcp-server-jupyter` (via `poetry build` or `python -m build`).
    2. Copies the resulting `.whl` into `vscode-extension/python_server/` for packaging.

- Kill the source-copy workflow.
  - The previous `vscode-extension/scripts/copy-python-server.js` is deprecated and exits with an error.
  - Do not commit Python source into the extension bundle.

- Remove `uv.lock` and standardize on `pyproject.toml` as the single source of dependency truth.

CI/CD Requirements
------------------

1. The GitHub Actions workflow that publishes the extension MUST call the same `bundle-python` script used locally (no clickops).
2. Add a CI step to build the wheel and publish it to your artifact storage (or wheel registry) as part of release pipelines.
3. Add Software Composition Analysis (Snyk/Dependabot/OSV) on lockfiles to detect transitive supply-chain risks.

Developer Notes
---------------

- To build locally (developer machine):

  ```sh
  # Build wheel (poetry preferred)
  cd tools/mcp-server-jupyter
  poetry build -f wheel -o dist

  # Then package extension
  cd ../../vscode-extension
  npm run vscode:prepublish
  ```

- If you maintain a legacy `requirements.txt` for portability, generate it from the lockfile; do NOT append to it at runtime.

Questions / Rollout
------------------
If you want, I can (A) update the GitHub Actions workflows to run the same build steps and artifact publishing, (B) implement a small `make release` target that standardizes builds, or (C) add a prepublish check that fails if the extension bundle contains Python source directories.

---


2. **DNS Requirement**
   - The MCP Server connects to kernels via Headless Service DNS (`jupyter-kernel-svc-<id>.<namespace>.svc.cluster.local`).
   - **Cluster:** Ensure CoreDNS is healthy and resolvable from the MCP Server pods.
   - **Local Dev:** If running the server locally against a remote cluster, you **must** use a tool like **Telepresence**, **a VPN**, or an equivalent solution that makes `.svc.cluster.local` resolvable locally.

3. **Label Requirement**
   - The NetworkPolicy only allows ingress from pods with the label `app: mcp-server-manager`.
   - Ensure your MCP Server Deployment applies this label to the Pod template (not just the Deployment metadata). Example:

```yaml
metadata:
  name: mcp-jupyter
spec:
  selector:
    matchLabels:
      app: mcp-server-manager
  template:
    metadata:
      labels:
        app: mcp-server-manager
```

4. **Operational Notes**
   - If you enable strict NetworkPolicy enforcement, confirm observability and network egress needs (DNS, package registries for pip, etc.) are included in the policy.
   - Document and validate these prerequisites in your rollout plan to avoid false-positive security alerts or connectivity outages.

---

## Singleton Architecture & Namespace best-practices

This service is stateful (manages kernels via RWO volume locks). Please be aware of the following operational constraints:

- **Do not scale replicas > 1.** Running multiple replicas will create split-brain scenarios where different server instances cannot coordinate kernel ownership.
- **Use `strategy: Recreate` for safe updates.** Recreate ensures the old pod terminates and releases RWO volumes before the new pod starts.
- **Namespace awareness:** The server uses the runtime `POD_NAMESPACE` (injected via Downward API) for DNS checks and service discovery. Ensure the Deployment injects this environment variable into the Pod template:

```yaml
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
```

**Why:** This avoids false positives/negatives when validating cluster DNS from a local dev machine or when deploying to non-default namespaces.

---


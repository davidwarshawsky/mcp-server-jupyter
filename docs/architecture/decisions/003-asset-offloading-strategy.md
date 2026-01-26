# ADR-003: Asset Offloading Strategy (Filesystem vs. Database Blobs)

**Date:** 2026-01-22
**Status:** Deprecated
**Deciders:** IIRB, Architecture Team

## Context

When tools produce large outputs (plots, CSVs, HTML reports, PDF exports), there are two strategies:

1. **Inline (Rejected):** Serialize as base64 or JSON and include in the MCP response. E.g., `{"result": "base64:iVBORw0KGgo..."}` (megabytes of JSON).
2. **Offloading (Current Implementation):** Write to filesystem, return a URI reference. E.g., `{"result": "/tmp/.mcp-jupyter/asset_12345.html", "mime": "text/html"}`.

## Decision

We have implemented **Filesystem Asset Offloading** as a temporary measure. This is a **known limitation** and not a long-term solution.

## Rationale

### Why the Current Implementation is a Problem

1. **Manual Cleanup:** The current implementation relies on a manual `--eject` command to clean up assets. This is a recipe for disaster. Users will forget to run it, and the `assets` directory will become a black hole of orphaned files.
2. **No Automated Lifecycle Management:** The current implementation has no automated lifecycle management. This means that assets will never be deleted unless the user manually runs the `--eject` command. This is a major security and privacy risk.
3. **No Support for Cloud Storage:** The current implementation only supports storing assets on the local filesystem. This is a major limitation for users who want to deploy the application in the cloud.

### The Future is Automated

We will be migrating to a more robust and automated solution as soon as possible. The new solution will feature automated lifecycle management, support for cloud storage, and a more user-friendly interface. We are actively researching and prototyping new solutions and will be creating a new ADR to document our chosen approach.

## Consequences

- **Good:** The current implementation is a working product.
- **Bad:** The current implementation is a security and privacy risk, and it is not scalable.
- **Action:** We will be migrating to a more robust and automated solution as soon as possible.

## References

- Plotly HTML assets: https://plotly.com/python/
- Bokeh server patterns: https://docs.bokeh.org/
- Asset lifecycle strategy: See `tools/mcp-server-jupyter/src/asset_manager.py`

# ADR-001: Handoff Protocol vs. CRDT (Conflict-free Replicated Data Types)

**Date:** 2026-01-22
**Status:** Accepted (with major caveats)
**Deciders:** IIRB, Architecture Team

## Context

When synchronizing notebook state between the VS Code extension (client) and the MCP server (Python kernel), there are two fundamental approaches:

1. **Handoff Protocol (Current Implementation):** Client sends lock request → server acquires lock → executes operation → releases lock → client continues.
2. **CRDT (Future Goal):** Both client and server maintain replicas of state, apply operations in causal order, automatically merge divergent branches.

## Decision

We have implemented a **Handoff Protocol with explicit locking** as a temporary measure due to its simplicity. However, this is a **known limitation** and not a long-term solution.

## Rationale

### Why Handoff Protocol Was Chosen (as a first step)

1. **Simplicity:** A handoff protocol is a simple, easy-to-implement solution that allowed us to get a working product up and running quickly.

### The Problem with Handoff Protocol

1. **No Real-Time Collaboration:** This approach makes real-time collaboration impossible. Only one user can edit the notebook at a time.
2. **Poor User Experience:** The locking mechanism can lead to a frustrating user experience, with users being blocked from editing the notebook while another user is making changes.
3. **Scalability Issues:** The locking mechanism is a bottleneck that will prevent the application from scaling to a large number of users.

## Future Plans

We will be migrating to a CRDT-based solution as soon as possible. This will enable real-time collaboration and provide a much better user experience. We are actively researching and prototyping CRDT implementations and will be creating a new ADR to document our chosen approach.

## Consequences

- **Good:** The current implementation is simple and easy to understand.
- **Bad:** The current implementation is not scalable and provides a poor user experience.
- **Action:** We will be migrating to a CRDT-based solution as soon as possible.

## References

- Yjs (CRDT library): https://docs.yjs.dev/
- Automerge (CRDT library): https://automerge.org/
- Jupyter Execution Model: https://docs.jupyter.org/en/latest/architecture/architecture.html

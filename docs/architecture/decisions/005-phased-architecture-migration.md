# 005: Phased Migration from Monolith to Service-Oriented Architecture

**Status:** Proposed

## Context

ADR-004 accepted a monolithic architecture for `mcp-server-jupyter` to accelerate initial development and simplify deployment. This was a pragmatic choice that allowed the project to achieve production readiness quickly.

However, as the project matures and its feature set expands, the monolithic approach presents long-term risks:

*   **Scalability Bottlenecks:** All components share the same resources, making it difficult to scale specific parts of the system (e.g., the execution scheduler) independently.
*   **Maintenance Overhead:** The growing codebase increases cognitive load for developers, slowing down feature development and bug fixes.
*   **Reduced Fault Isolation:** A crash in one component (e.g., a memory leak in the asset manager) can bring down the entire server, impacting all users.
*   **Technology Lock-in:** A monolith makes it harder to adopt new technologies for specific components without impacting the entire system.

This ADR proposes a path forward to mitigate these risks and ensure the project's long-term health and scalability.

## Decision

We will adopt a phased migration strategy to evolve the `mcp-server-jupyter` monolith into a more modular, Service-Oriented Architecture (SOA).

This will be achieved by progressively identifying core domains within the monolith and extracting them into separate, independently deployable services that communicate over well-defined APIs.

This approach allows us to deliver incremental value and manage risk, rather than attempting a high-risk "big bang" rewrite.

## Phased Migration Plan

### Phase 1: Internal Decomposition (Refactoring)

**Goal:** Logically separate service boundaries *within* the existing monolith.

*   **Action:** Refactor the current codebase to group related modules into distinct "internal service" packages. No new services will be deployed in this phase.
*   **Identified Domains:**
    *   `KernelManagement`: Responsible for the lifecycle of Jupyter kernels.
    *   `ExecutionScheduling`: Manages the Directed Acyclic Graph (DAG) of cell executions.
    *   `SessionState`: Handles notebook state and persistence.
    *   `AssetManagement`: Manages large outputs and file I/O.
*   **Outcome:** A cleaner, more modular monolith with clear API boundaries between domains, paving the way for future extraction. This is a low-risk, high-value refactoring effort.

### Phase 2: Extract the Execution Scheduler Service

**Goal:** Extract the first service to improve fault isolation for a critical component.

*   **Action:** Create a new, independent service (`mcp-scheduler-service`) from the `ExecutionScheduling` domain. The main monolith will communicate with this service via a lightweight internal API (e.g., gRPC).
*   **Rationale:** The scheduler is a complex, stateful, and computationally intensive component. Isolating it prevents scheduler bugs from crashing the main server and allows it to be scaled independently if needed.
*   **Outcome:** Two services: the main `mcp-server-jupyter` (now slightly smaller) and the new `mcp-scheduler-service`.

### Phase 3: Extract the Asset Manager Service

**Goal:** Isolate I/O-intensive operations to enable independent scaling of storage resources.

*   **Action:** Create a new `mcp-asset-service` from the `AssetManagement` domain. This service will handle all large output storage and retrieval.
*   **Rationale:** Asset management has unique resource requirements (disk I/O, network bandwidth). Separating it allows us to optimize its infrastructure (e.g., dedicated object storage, CDNs) without impacting the core application.
*   **Outcome:** Three services, each with a well-defined responsibility, improving the overall resilience and scalability of the system.

## Consequences

### Positive

*   **Improved Scalability:** Components can be scaled independently based on their specific needs.
*   **Enhanced Resilience:** Faults are isolated, preventing a single component failure from causing a total system outage.
*   **Increased Development Velocity:** Teams can develop, test, and deploy services independently, reducing cognitive load and release cycle times.
*   **Future-Proofing:** A service-oriented architecture makes it easier to adopt new technologies and implement large-scale features (like the CRDT-based multi-user support mentioned in the IIRB remediation backlog).

### Negative

*   **Increased Operational Complexity:** We will have more services to deploy, monitor, and secure. This requires investment in our CI/CD pipeline and observability stack (e.g., centralized logging and tracing).
*   **Network Latency:** Communication between services introduces network overhead. This will be mitigated by using efficient protocols (like gRPC) and carefully designing service boundaries.

This phased migration represents a strategic investment in the long-term health and success of MCP Jupyter.

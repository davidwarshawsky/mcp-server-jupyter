# ADR-004: Monolithic Architecture

**Date:** 2026-01-22
**Status:** Proposed
**Deciders:** IIRB, Architecture Team

## Context

The current split-topology architecture (ADR-002) is a major source of complexity and risk. It is difficult to maintain, and it slows down development. We need to move to a monolithic architecture to simplify the project, reduce the risk of errors, and speed up development.

## Decision

We will be migrating to a monolithic architecture. The new architecture will be based on a single codebase, a single build system, and a single set of dependencies.

## Rationale

### Why a Monolithic Architecture is Better

1. **Reduced Complexity:** A monolithic architecture is much simpler than a split-topology architecture. We will have a single codebase, a single build system, and a single set of dependencies. This will make the project much easier to develop, test, and maintain.
2. **Reduced Risk of Errors:** A monolithic architecture reduces the risk of errors. We will have a single runtime, a single set of libraries, and a single set of APIs. This will make it much less likely that we will introduce bugs.
3. **Faster Development:** A monolithic architecture will speed up development. We will be able to spend more time developing new features and less time managing the complexity of the split-topology architecture.

## Phased Migration Plan

We will be migrating to a monolithic architecture in a phased approach. The first phase will be to create a new, unified codebase. The new codebase will be based on Python, and it will use the new `nbformat` library to communicate with the Jupyter kernel. The second phase will be to migrate the existing features to the new codebase. The third phase will be to deprecate the old codebase.

### Phase 1: New Codebase

- Create a new, unified codebase based on Python.
- Use the new `nbformat` library to communicate with the Jupyter kernel.

### Phase 2: Migrate Features

- Migrate the existing features to the new codebase.

### Phase 3: Deprecate Old Codebase

- Deprecate the old codebase.

## Consequences

- **Good:** A simpler, more robust, and more maintainable architecture.
- **Bad:** A significant amount of work to migrate to the new architecture.
- **Action:** We will begin work on the new architecture immediately.

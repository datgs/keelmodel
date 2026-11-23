---
status: proposed
last_reviewed: 2026-11-20
superseded_by: []
related_code: []
---

# Brainstorm: KeelModel Module Registry

## Decision

- **Recommendation:** KeelModel provides explicit module registration, Python entry-point discovery, and a metadata registry. Modules register model and DataView definitions in code. Scaffold tools consume the same registry used by runtime.
- **Decision owner:** User
- **Confidence:** medium — Python packaging entry points are a standard discovery mechanism; KeelModel's module contract is not implemented or tested yet.

## Problem and Outcome

KeelModel modules may live in separate repositories and packages. Runtime and scaffold need one consistent way to discover registered definitions without scanning arbitrary source files.

## Constraints and Non-Goals

- Applications install and version module packages through Python packaging.
- Loading modules is explicit through registration; discovery does not fetch source code.
- Scaffold can inspect metadata without creating database connections or running migrations.
- Module registration must not depend on UI behavior.

## Evidence

- Python Packaging User Guide documents entry points as package metadata for plugin discovery and loading: https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/.
- Python `importlib.metadata` exposes installed package entry points.

## Meaningful Alternatives

### Scan source directories

- **When it is better:** Only for a tightly controlled, single-repository tool with a fixed module layout.
- **Why not now:** Separate packages and arbitrary imports make scanning less explicit and potentially execute unrelated code.

## Trade-offs and Risks

| Item | Impact | Response |
|---|---|---|
| Entry-point loading imports module code | medium | Keep discovery and loading explicit; registration should only declare definitions. |
| Installed packages may have incompatible module APIs | medium | Define module metadata and compatibility checks before broad adoption. |

## Assumptions and Open Questions

- Modules are installed into the application's Python environment before discovery.
- Exact registration API, manifest fields, version constraints, duplicate-name handling, and loading error policy remain open.
- **Falsifying signal:** Scaffold must discover uninstalled source packages in a supported workflow.

## Security Considerations

Loading an entry point executes package code. Only load trusted installed modules and make the load step explicit.

## Revisit Trigger

Revisit if modules must be inspected without importing executable Python code or discovered directly from source repositories.

## Next Step

When requested, define the module contract and scaffold discovery workflow in an implementation plan.

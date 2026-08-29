# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## Repository Simplification

1. Audit workloads for avoidable init containers, sidecars and lifecycle
   workarounds. Prefer direct workload configuration when it provides the
   required behaviour; keep helper containers only when they own a distinct
   runtime responsibility.

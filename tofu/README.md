# OpenTofu

These stacks manage only cluster substrate. Kubernetes resources remain under
Flux, and app-facing external APIs will use direct Crossplane HTTP resources.

Each directory is an independent state and blast radius. Initialise and plan
one directory at a time. Never run an apply from the repository root.

- `bootstrap`: the existing GCS state bucket, after an explicit import.
- `au-oci`: a read-only audit of the existing OCI host until state ownership is
  transferred from the `homelab` repository.
- `truenas`: the future TrueNAS VM import boundary; deliberately has no
  provider configuration yet.

Provider credentials come from their normal environment or CLI configuration.
Do not pass private keys or tokens as OpenTofu variables, because values can be
recorded in state and plan files.

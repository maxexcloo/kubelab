# Kubelab

Kubelab is the GitOps source of truth for a two-cluster Talos Kubernetes
homelab. It is both a real migration and a practical Kubernetes learning
environment.

The first cluster is `au-home`, a single Talos VM on TrueNAS. Once it proves
rebuilds, Flux, networking, HTTP, secrets, storage, and recovery, the empty OCI
Sydney host becomes the independent `au-hsp` cluster. Hotdog remains a small
ZFS backup appliance and Bazzite remains an optional Podman/GPU worker.

Read [plan.md](plan.md) for architecture, ownership, migration gates, and
recovery. Nothing in CI deploys a cluster: validation runs in GitHub Actions,
while Flux pulls approved state from Git.

## First setup

```shell
mise trust
mise run setup
mise run check
```

`mise.toml` pins the local toolchain. The main commands are:

- `mise run check`: fast formatting and configuration checks.
- `mise run prek`: the complete local equivalent of CI.
- `mise run fmt`: apply project formatting.
- `mise run plan`: create reviewed, non-destructive OpenTofu plans for
  initialised stacks; it never applies them.

## Learning sequence

Each stage is intentionally observable before the next abstraction is added:

1. Talos teaches immutable node configuration and Kubernetes bootstrap.
2. A direct OpenSpeedTest Deployment and Service teach Pods, reconciliation,
   stable service discovery, probes, and resource requests.
3. Flux teaches pull-based reconciliation and dependency ordering.
4. Cilium and Hubble teach Pod networking, policy, and flow visibility.
5. Gateway API and Traefik teach HTTP routing independently of the proxy.
6. External Secrets teaches secret references without committing values.
7. Static NFS teaches persistent volumes before a CSI driver automates them.
8. Crossplane HTTP resources teach external API reconciliation only after the
   cluster itself is understood.

The repository will stop at the review gates in `plan.md` before destructive
host resets, live routes, or infrastructure applies.

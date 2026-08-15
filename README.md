# Kubelab

Kubelab is the Kubernetes and Flux GitOps source of truth for a two-cluster
homelab. It is both a real migration and a practical Kubernetes learning
environment. It owns workloads and app-scoped integrations; the separate
`homelab` repository owns everything required to rebuild or reach a cluster
while Kubernetes is unavailable.

The first cluster is `mbk`, with the single Taco Talos VM on TrueNAS. Once it proves
rebuilds, Flux, networking, HTTP, secrets, storage, and recovery, the empty OCI
Sydney HSP host becomes the independent `syd` cluster. Hotdog remains a small
ZFS backup appliance and Mandu remains an optional Bazzite Podman/GPU worker.

Read [PLAN.md](PLAN.md) for architecture, ownership, migration gates, and
recovery. Nothing in CI deploys a cluster: validation runs in GitHub Actions,
while Flux pulls approved state from Git.

The guided implementation starts in [docs/bootstrap.md](docs/bootstrap.md).
It explains the Talos, Cilium, and Flux bootstrap boundary and the checks to
perform before adding another controller.

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

## Learning sequence

Each stage is intentionally observable before the next abstraction is added:

1. The `homelab` handoff provides a healthy Kubernetes API and kubeconfig.
2. A direct OpenSpeedTest Deployment and Service teach Pods, reconciliation,
   stable service discovery, probes, and resource requests.
3. Flux teaches pull-based reconciliation and dependency ordering.
4. Cilium and Hubble teach Pod networking, policy, and flow visibility.
5. Gateway API and Traefik teach HTTP routing independently of the proxy.
6. External Secrets teaches secret references without committing values.
7. Static NFS teaches persistent volumes before a CSI driver automates them.
8. Crossplane HTTP resources teach external API reconciliation only after the
   cluster itself is understood.

The repository will stop at the review gates in `PLAN.md` before live routes or
workload cutovers. Destructive host and infrastructure gates live in
`homelab`.

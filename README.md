# Kubelab

Kubernetes API resources and Flux GitOps configuration for a two-cluster homelab.
Cluster substrate and recovery foundations live in the separate `homelab` repository.

## Clusters

- **`mbk`**: Single-node Talos control plane and primary workloads running in a TrueNAS
  VM (`taco`) with NVMe-backed NFS storage.
- **`syd`**: Independent cloud Talos control plane and secondary workloads running on
  Oracle Cloud Infrastructure (OCI) Ampere A1 (`hsp`).

## Quick Start

Tooling is pinned and managed through [Mise](https://mise.jdx.dev/):

```shell
mise trust
mise run setup
mise run check
```

### Common Tasks

| Task             | Description                                                          |
| ---------------- | -------------------------------------------------------------------- |
| `mise run check` | Run validation suite (Kubernetes schemas, formatting, security scan) |
| `mise run fmt`   | Format project files (Prettier)                                      |
| `mise run prek`  | Run all Git pre-commit hooks across the repository                   |
| `mise run setup` | Install tools and Git hooks                                          |

## Architecture & Governance

- Read [PLAN.md](PLAN.md) for cross-repository ordering, workload ownership, and cutover gates.
- Follow [docs/bootstrap.md](docs/bootstrap.md) for initial cluster bootstrap and verification.
- Inventory and cutover status is tracked in [docs/migration-inventory.md](docs/migration-inventory.md).
- GitHub Actions validates syntax and policies on pull requests; reconciliation occurs entirely via Flux pulling Git.

## Learning Sequence

Each layer is intentionally observable before adding the next:

1. **Substrate**: The `homelab` handoff provides a healthy Kubernetes API and kubeconfig.
2. **Workload**: A direct OpenSpeedTest Deployment and Service teach Pods, reconciliation, stable service discovery, probes, and resource requests.
3. **GitOps**: Flux teaches pull-based reconciliation and dependency ordering.
4. **Networking**: Cilium and Hubble teach Pod networking, policy, and flow visibility.
5. **Ingress & HTTP**: Gateway API and Traefik teach HTTP routing independently of the proxy.
6. **Secrets**: External Secrets Operator teaches secret references without committing values.
7. **Storage**: Static NFS teaches persistent volumes before a CSI driver automates them.
8. **Platform APIs**: Crossplane HTTP resources teach external API reconciliation only after the cluster itself is understood.

## Licence

AGPL-3.0 - see [LICENSE](LICENSE).

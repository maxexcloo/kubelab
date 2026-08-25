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

| Task                 | Description                                                          |
| -------------------- | -------------------------------------------------------------------- |
| `mise run bootstrap` | Bootstrap the current Kubernetes context in dependency order         |
| `mise run check`     | Run validation suite (Kubernetes schemas, formatting, security scan) |
| `mise run fmt`       | Format project files (Prettier)                                      |
| `mise run prek`      | Run all Git pre-commit hooks across the repository                   |
| `mise run setup`     | Install tools and Git hooks                                          |

## Bootstrap

After substrate provisioning in `homelab`:

```shell
mise run bootstrap
```

The task shows the current Kubernetes context and API endpoint before asking for
confirmation. It installs Cilium, injects the cluster's provisioned
1Password Connect credentials, and reconciles Flux through the ordered
`bootstrap-cilium`, `bootstrap-secrets`, and `bootstrap-flux` dependency chain.

## Platform

- **GitOps & Reconciliation**: Flux controllers pull and reconcile manifests declaratively from Git.
- **Networking & Ingress**: Cilium CNI, ExternalDNS, Hubble network observability, isolated Traefik Gateway API entrypoints, and Cloudflared tunnels.
- **Observability**: VictoriaMetrics, VictoriaLogs, and Grafana for replaceable cluster metrics and logs.
- **Security & Certificates**: cert-manager DNS-01 ACME certificates and External Secrets Operator backed by 1Password SDK.
- **Identity & Management**: Headlamp web UI with least-privilege access.
- **Storage**: Replaceable node-local volumes on both clusters and retained TrueNAS NVMe NFS volumes on `mbk`.

## Operations & Safety

- **Declarative GitOps**: CI validates syntax and security; Flux pulls and reconciles state without CI write credentials.
- **Dependency Ordering**: CRDs install first, platform controllers second, and workloads last.
- **Secret Hygiene**: Zero secret values in Git; all credentials resolve via ExternalSecrets from 1Password vaults.

## Licence

AGPL-3.0 - see [LICENSE](LICENSE).

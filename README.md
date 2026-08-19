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

## Bootstrap

After substrate provisioning in `homelab`:

1. **Verify API Access**:
   ```shell
   kubectl --context <cluster> get nodes
   ```
2. **Bootstrap Cilium CNI**:
   ```shell
   helm repo add cilium https://helm.cilium.io
   helm upgrade --install cilium cilium/cilium \
     --kube-context <cluster> \
     --namespace kube-system \
     --version 1.20.0 \
     --values platform/networking/cilium/values.yaml
   ```
3. **Inject 1Password Bootstrap Secret**:
   ```shell
   mise -C ../homelab run bootstrap-secrets
   ```
4. **Bootstrap Flux**:
   ```shell
   kubectl --context <cluster> apply --server-side --kustomize clusters/<cluster>/flux-system
   ```

## Platform

- **GitOps & Reconciliation**: Flux controllers pull and reconcile manifests declaratively from Git.
- **Networking & Ingress**: Cilium CNI, Hubble observability, Traefik Gateway API controller, and Cloudflared tunnels.
- **Security & Certificates**: cert-manager DNS-01 ACME certificates and External Secrets Operator backed by 1Password SDK.
- **Identity & Management**: Headlamp web UI with least-privilege access.
- **Storage**: Retained TrueNAS NVMe NFS persistent volumes and storage classes.

## Operations & Safety

- **Declarative GitOps**: CI validates syntax and security; Flux pulls and reconciles state without CI write credentials.
- **Dependency Ordering**: CRDs install first, platform controllers second, and workloads last.
- **Secret Hygiene**: Zero secret values in Git; all credentials resolve via ExternalSecrets from 1Password vaults.

## Licence

AGPL-3.0 - see [LICENSE](LICENSE).

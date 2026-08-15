# Cluster Bootstrap

Bootstrap `mbk` first. Do not reset `hsp` for `syd` until the home-cluster
gate in [PLAN.md](../PLAN.md) passes.

## Substrate handoff

The `homelab` OpenTofu stack owns the Talos image, system extensions, machine
secrets, machine configuration, installation, bootstrap, and recovery
material. Before starting here, verify its exit checks and have the generated
administrator `kubeconfig` in an encrypted working store outside this
repository.

The Git source is public and requires no deploy key for reconciliation. Keep any
workstation GitHub credential used to push the generated bootstrap manifests in
the operator's normal 1Password-backed Git tooling, not in the cluster.

Also confirm that the committed Pod and Service CIDRs do not overlap any LAN,
OCI, Tailscale, container, TrueNAS, or client VPN network.

## 1. Verify the Kubernetes handoff

The node is expected to remain NotReady until its CNI is installed. The
Kubernetes API and control-plane system Pods must still be reachable enough to
install Cilium. Stop here and fix the `homelab` substrate if either command
cannot reach the intended cluster:

```shell
kubectl get nodes
kubectl get pods --all-namespaces
```

## 2. Bootstrap Cilium

Talos is configured with `cni.name: none`. The Kubernetes API becomes
available before Pods can network, so Cilium is the one platform chart that
must be installed before Flux:

```shell
helm repo add cilium https://helm.cilium.io
helm repo update cilium
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.20.0 \
  --values platform/networking/cilium/values.yaml
kubectl --namespace kube-system rollout status daemonset/cilium
kubectl --namespace kube-system rollout status deployment/cilium-operator
```

The values are the same values committed for the Flux `HelmRelease`. The
release name and namespace also match, so Flux adopts the existing Helm release
instead of installing a second copy. Run `mise run check` before bootstrap; it
fails when the bootstrap values and `HelmRelease` values differ.

Check node and system health before continuing:

```shell
kubectl get nodes
kubectl get pods --all-namespaces
kubectl --namespace kube-system exec daemonset/cilium -- cilium-dbg status
```

## 3. Bootstrap Flux

The public Git remote is `https://github.com/maxexcloo/kubelab`. Generate the
pinned controllers and unauthenticated HTTPS source with Flux, commit and push
them, then apply the committed bootstrap directory:

```shell
flux install --version v2.9.4 --export
flux create source git flux-system \
  --url https://github.com/maxexcloo/kubelab \
  --branch main \
  --interval 1m \
  --export
flux create kustomization flux-system \
  --source GitRepository/flux-system \
  --path ./clusters/mbk \
  --prune \
  --interval 10m \
  --retry-interval 2m \
  --wait \
  --export
kubectl apply --server-side --kustomize clusters/mbk/flux-system
```

The generated output is committed under `clusters/mbk/flux-system`; never put
a GitHub token in those files. Do not use `flux bootstrap github` here because
it creates a deploy key or persists token authentication that a public source
does not need. Flux will adopt Cilium and reconcile the remaining platform and
workload resources from the cluster path.
The committed Flux dependencies install Gateway API CRDs first, wait for the
platform controllers including Traefik second, and apply applications last.
This prevents custom resources from racing the controllers that define them.

## 4. Observe reconciliation

```shell
flux check
flux get sources all --all-namespaces
flux get helmreleases --all-namespaces
kubectl get events --all-namespaces --sort-by=.lastTimestamp
```

Stop and diagnose any unhealthy resource before adding the next platform
controller. The learning objective is to understand each reconciliation layer,
not merely to reach a green dashboard.

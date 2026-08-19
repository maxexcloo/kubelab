# Cluster Bootstrap

Bootstrap `mbk` first. Do not reset `hsp` for `syd` until the home-cluster
gate in [PLAN.md](../PLAN.md) passes.

## Substrate handoff

The `homelab` OpenTofu stack owns the Talos image, system extensions, machine
secrets, machine configuration, installation, bootstrap, and recovery
material. Before starting here, verify its exit checks and synchronise your
workstation `kubeconfig` and `talosconfig` from 1Password:

```shell
mise run client-configs # in the homelab repository
```

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
kubectl --context <cluster> get nodes
kubectl --context <cluster> get pods --all-namespaces
```

## 2. Bootstrap Cilium

Talos is configured with `cni.name: none`. The Kubernetes API becomes
available before Pods can network, so Cilium is the one platform chart that
must be installed before Flux:

```shell
helm repo add cilium https://helm.cilium.io
helm repo update cilium
helm upgrade --install cilium cilium/cilium \
  --kube-context <cluster> \
  --namespace kube-system \
  --version 1.20.0 \
  --values platform/networking/cilium/values.yaml
kubectl --context <cluster> --namespace kube-system rollout status daemonset/cilium
kubectl --context <cluster> --namespace kube-system rollout status deployment/cilium-operator
```

The values are the same values committed for the Flux `HelmRelease`. The
release name and namespace also match, so Flux adopts the existing Helm release
instead of installing a second copy. Run `mise run check` before bootstrap; it
fails when the bootstrap values and `HelmRelease` values differ.

Check node and system health before continuing:

```shell
kubectl --context <cluster> get nodes
kubectl --context <cluster> get pods --all-namespaces
kubectl --context <cluster> --namespace kube-system exec daemonset/cilium -- cilium-dbg status
```

## 3. Inject the 1Password SDK bootstrap secret

External Secrets Operator requires a bootstrap service-account token to
authenticate to 1Password and synchronise cluster secrets:

```shell
kubectl --context <cluster> create namespace external-secrets --dry-run=client -o yaml | kubectl --context <cluster> apply -f -

kubectl --context <cluster> -n external-secrets create secret generic onepassword-sdk \
  --from-literal=token="$(op item get --vault "Homelab" "Service Account Auth Token: <cluster>-eso" --fields credential)" \
  --dry-run=client -o yaml | kubectl --context <cluster> apply -f -
```

## 4. Bootstrap Flux

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
  --path ./clusters/<cluster> \
  --prune \
  --interval 10m \
  --retry-interval 2m \
  --wait \
  --export
kubectl --context <cluster> apply --server-side --kustomize clusters/<cluster>/flux-system
```

The generated output is committed under `clusters/<cluster>/flux-system`; never put
a GitHub token in those files. Do not use `flux bootstrap github` here because
it creates a deploy key or persists token authentication that a public source
does not need.

Flux will adopt Cilium and reconcile the remaining platform and workload
resources from the cluster path. The committed Flux dependencies install
CRDs first (`platform/crds`), wait for platform controllers and integrations
second, and apply applications last. This prevents custom resources from racing
the controllers and CRDs that define them.

## 5. Observe reconciliation

```shell
flux --context <cluster> check
flux --context <cluster> get sources all --all-namespaces
flux --context <cluster> get kustomizations
flux --context <cluster> get helmreleases --all-namespaces
kubectl --context <cluster> get events --all-namespaces --sort-by=.lastTimestamp
```

Stop and diagnose any unhealthy resource before adding the next platform
controller. The learning objective is to understand each reconciliation layer,
not merely to reach a green dashboard.

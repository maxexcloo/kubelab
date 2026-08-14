# Cluster Bootstrap

Bootstrap `au` first. Do not reset `hsp` for `au-oci` until the home-cluster
gate in [plan.md](../plan.md) passes.

## Inputs kept outside Git

Before starting, have these in 1Password or another encrypted working store:

- Talos machine secrets and `talosconfig`;
- the generated administrator `kubeconfig`;
- a Tailscale auth key for the Talos system extension; and
- the Git repository URL and Flux authentication material.

Also confirm that the committed Pod and Service CIDRs do not overlap any LAN,
OCI, Tailscale, container, TrueNAS, or client VPN network.

## 1. Install Talos

Follow [the Talos instructions](../talos/README.md) to build the official image,
generate configuration, validate it, apply it to the VM, and bootstrap etcd.
Keep all generated secrets outside this repository.

## 2. Bootstrap Cilium

Talos is configured with `cni.name: none`. The Kubernetes API becomes
available before Pods can network, so Cilium is the one platform chart that
must be installed before Flux:

```shell
helm repo add cilium https://helm.cilium.io
helm repo update cilium
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.19.6 \
  --values platform/networking/cilium/values.yaml
kubectl --namespace kube-system rollout status daemonset/cilium
kubectl --namespace kube-system rollout status deployment/cilium-operator
```

The values are the same values committed for the Flux `HelmRelease`. The
release name and namespace also match, so Flux adopts the existing Helm release
instead of installing a second copy.

Check node and system health before continuing:

```shell
kubectl get nodes
kubectl get pods --all-namespaces
kubectl --namespace kube-system exec daemonset/cilium -- cilium-dbg status
```

## 3. Bootstrap Flux

This repository does not yet have a Git remote, so do not invent a repository
URL or credentials. Once the remote exists, use Flux's standard bootstrap
command for that Git provider and set its path to the relevant cluster:

- `clusters/au` for the TrueNAS VM; or
- `clusters/au-oci` for the OCI host after its migration gate passes.

Commit the generated `flux-system` manifests. Flux will then adopt Cilium and
reconcile the remaining platform and workload resources from the cluster path.

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

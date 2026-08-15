# Kubernetes Homelab Migration Plan

## Status

This document is authoritative for cross-repository migration ordering,
workload ownership, and cutover gates. It replaces the disposable local-cluster
plan. The separate `homelab/PLAN.md` is authoritative for implementation inside
that repository, including state layout, providers, cluster compute, Talos, and
recovery access. A repository-scoped plan may add detail but must not redefine
the ordering or ownership recorded here.

The first implementation target is a single-node Talos cluster in a TrueNAS
virtual machine. This repository owns Kubernetes workloads and their app-scoped
integrations. The `homelab` repository owns everything required to rebuild or
reach a cluster while Kubernetes is unavailable, including the VM, network,
Talos lifecycle, bootstrap, recovery credentials, and access foundations. The
trial must prove GitOps, networking, storage, secrets, recovery, and one
disposable workload before the existing Sydney OCI host (`hsp`) is reset. No
valued workload is removed until its replacement passes the applicable
migration gate.

Git history is the implementation log. Changes use small, imperative commits
that record one coherent outcome. This complete plan is the first commit and
contains no implementation files.

## Goals

- Learn Kubernetes, Talos, Flux, Helm, Gateway API, storage, policy, and
  day-two operations through the real homelab migration.
- Keep Kubernetes reproducible from this Git repository and cluster substrate
  reproducible from the separate `homelab` repository.
- Prefer stock upstream components, official charts, and small configuration
  surfaces.
- Keep GitHub Actions optional: CI validates changes and may build uncommon
  images, but never deploys a cluster.
- Preserve private access through Tailscale and public HTTP access through
  Cloudflare Tunnel.
- Preserve 1Password secrets, Pocket ID OIDC, Resend mail, Backblaze B2 object
  storage, Fly-hosted monitoring, Homepage, backups, and existing appliances.
- Maintain and validate aligned Homepage entries and Gatus probes using direct
  configuration and native Kubernetes discovery.
- Make ownership, deletion behaviour, recovery, and cutover explicit for every
  external resource and stateful service.

## Non-goals

- A stretched Kubernetes cluster across home, Sydney OCI, and the United
  States.
- Artificial high availability on one physical TrueNAS host or one OCI VM.
- Running Talos on the 2 GB Hotdog backup receiver.
- Replacing Bazzite or making its GPU a permanent Kubernetes node.
- Self-hosting Omni or Rancher during this migration.
- Using Kubernetes or Crossplane to own the infrastructure on which the
  Kubernetes control plane depends.
- Hiding migrations behind a large internal platform or custom operator.

## Fixed Architecture

### Failure domains

| Name | Location | Shape | Role | Storage |
| --- | --- | --- | --- | --- |
| `mbk` | Taco VM on TrueNAS at home | 12 vCPU, 32 GiB RAM, 64 GiB boot disk | Single-node Talos control plane and primary workloads | TrueNAS NFS plus local scratch |
| `syd` | HSP VM on OCI Sydney | Ampere A1, 2 OCPU, 12 GiB RAM, 64 GiB boot disk | Single-node Talos control plane and independent secondary workloads | Local-path, replaceable data only |
| `hotdog` | United States | Existing Linux host, 2 GB RAM | ZFS replication receiver and host-monitored appliance | Existing ZFS |
| `mandu` | Home | Existing Bazzite workstation with AMD RX 6000 GPU | Opportunistic rootless Podman worker | Existing local storage |

Both Kubernetes clusters schedule workloads on their control-plane node. They
are deliberately independent; a WAN failure cannot break etcd quorum. The
home cluster shares a failure domain with TrueNAS compute and storage. This is
accepted for the initial design and is not described as high availability.

### Verified home trial substrate

The 2026-08-14 read-only inventory established the following facts before any
VM or network change:

- TrueNAS is a WTR PRO with 16 CPU cores and about 64 GiB RAM, running
  `26.0.0-BETA.2`. The existing beta installation is not changed as part of
  the Kubernetes trial.
- Pools `truenas` and `truenas-nvme` are online. The NVMe pool has about
  4.9 TB free and is the preferred location for the trial VM boot zvol.
- `eno1` serves `10.0.0.3/22` on the untagged UniFi `Default` network.
  `enp3s0` serves `10.4.0.3/22` on the separate UniFi `Services` network,
  VLAN 4, reserved for hosts' second interfaces.
- No VMs or Linux bridges exist. TrueNAS reports hardware virtualisation and
  UEFI support.
- The workstation route inventory confirms that the proposed
  `10.100.0.0/20` cluster range does not overlap the home LAN, either TrueNAS
  network, Tailscale, or local container networks. The independent OCI VCN is
  `10.20.0.0/16` and its initial subnet is `10.20.0.0/24`.

A TrueNAS bridge is a prerequisite for the trial. Do not attach the VM through
MACVLAN because Linux host-to-guest communication is restricted and the node
must mount storage from its TrueNAS host. Create `br4` with `enp3s0` as its
only member and move `10.4.0.3/22` from `enp3s0` to `br4` using TrueNAS staged
network changes. Keep `eno1` and `10.0.0.3/22` unchanged as the management and
rollback path. Attach the VM NIC to `br4`, let Talos maintenance mode obtain
its first address through DHCP, then reserve the currently unused `10.4.0.4`
for that NIC in UniFi before generating endpoint-specific Talos configuration.
`mbk` is the Kubernetes cluster identifier. Its TrueNAS VM and Talos node are
named `taco`, with canonical FQDN `taco.mbk.excloo.net`.

Bazzite also has a second physical NIC. It may later join the `Services`
network for direct storage and opt-in workload traffic, but that is independent
of the Talos trial and does not make Bazzite a Kubernetes node.

The Bazzite host uses rootless Podman Quadlets for opt-in jobs such as ComfyUI.
It communicates over Tailscale and is advertised to Homepage and monitoring,
but it is not joined to Kubernetes. The first ROCm trial is container-only and
must not change the Bazzite kernel or host GPU driver.

### Cluster networking

| Network | CIDR |
| --- | --- |
| `mbk` Pods | `10.100.0.0/22` |
| `mbk` Services | `10.100.4.0/22` |
| `syd` Pods | `10.100.8.0/22` |
| `syd` Services | `10.100.12.0/22` |

Before bootstrap, verify that `10.100.0.0/20` does not overlap the LAN, OCI,
Tailscale routes, Docker/Podman networks, TrueNAS networks, or VPN client
routes. An overlap stops bootstrap until new ranges are selected.

The initial CNI is Cilium with Hubble. Keep kube-proxy enabled during the
migration to reduce the number of simultaneous networking changes. Enforce
default-deny NetworkPolicies only after DNS, ingress, storage, secret, and
observability flows have documented allow rules.

There is no MetalLB initially. Each cluster has two ingress paths:

- Private: Traefik implementing Kubernetes Gateway API, exposed through the
  Tailscale Kubernetes operator. Control D provides split DNS for private
  `*.excloo.dev` service names.
- Public: a cluster-specific `cloudflared` deployment and Cloudflare Tunnel.
  Only explicitly labelled HTTPRoutes are published.

Talos management uses the Tailscale Talos extension. Kubernetes application
and API access uses the Tailscale operator. Stable LAN addressing for the home
VM is provided by a UniFi DHCP reservation; do not hard-code an unreserved
address in Talos configuration.

### HTTP and identity

Traefik is the only in-cluster HTTP proxy. Use Gateway API `Gateway` and
`HTTPRoute` resources rather than controller-specific Ingress annotations.
Install Gateway API CRDs independently because the Traefik chart does not own
their lifecycle.

Private services are the default. Public exposure requires an explicit
HTTPRoute and Cloudflare Tunnel route, TLS, monitoring, and an owner. Cloudflare
Access, WAF, and rate limiting are attached per application where appropriate.

Use `excloo.net` for infrastructure names and `excloo.dev` for APIs and
services. Kubernetes services use cluster-qualified names such as
`<service>.mbk.excloo.dev` and `<service>.syd.excloo.dev`. Exposure policy and
split DNS determine whether a service is public or private; the TLD does not.
Each legacy hostname migrates individually and remains available until the new
route is healthy and its rollback window expires.

Pocket ID remains the OIDC provider and ultimately runs in `mbk`. One
Headlamp instance runs in each cluster and authenticates through the
Kubernetes API server's Pocket ID OIDC configuration. Do not give Headlamp a
broad static service-account token. Store a tested cluster-admin break-glass
kubeconfig and Pocket ID recovery material in 1Password because home failure
also removes normal OIDC.

### Storage

The home cluster uses three explicit storage classes:

- `truenas-nfs`: dynamic or static NFS for `ReadWriteMany` data and large
  libraries.
- `truenas-iscsi`: iSCSI `ReadWriteOnce` block storage for databases where its
  driver is proven safe on Talos.
- `local-scratch`: node-local, disposable cache and test data.

All TrueNAS-backed persistent volumes use `Retain`. Database workloads use
single-instance CloudNativePG clusters unless the application's official chart
has a simpler supported database model. A replica on the same physical host is
not counted as high availability.

There is no official TrueNAS Kubernetes CSI driver to assume. Start the trial
with a static NFS persistent volume. Evaluate `democratic-csi` for NFS and
iSCSI only after confirming TrueNAS 26.0 API compatibility, Talos system
extensions, snapshot behaviour, retained-volume recovery, and upgrade health.
The experimental API-only drivers are not production defaults. Record that
decision before migrating a database.

`syd` uses local-path storage only for replaceable state, caches, and replicas of
data whose authority is elsewhere. It must not become the only copy of valued
data.

## Ownership and Configuration Contracts

### Control-plane ownership

| Concern | Authoritative owner | Notes |
| --- | --- | --- |
| OCI VCN, subnet, NSG, Talos image, and `hsp` VM | OpenTofu | Root `homelab` state; reviewed saved plan before apply |
| TrueNAS trial VM | Manual, then OpenTofu if import is drift-free | Protect imported VM from destruction |
| Existing GCS state bucket | External bootstrap prerequisite | No root backed by the bucket may manage it |
| Shared state IAM and access foundations | `homelab` foundations OpenTofu | Versioning, retention, and least privilege verified before use |
| Global Tailscale ACLs/grants and tag owners | `homelab` foundations OpenTofu | Shared access policy must survive either cluster |
| Tailscale operator OAuth client | Cluster-specific `homelab` OpenTofu | Separate least-privilege credential for each cluster |
| Talos node Tailscale extension and bootstrap identity | Cluster-specific `homelab` OpenTofu | Host-level recovery path; extension is baked into each Talos image |
| Tailscale Kubernetes operator | Flux in `kubelab` | In-cluster application and Kubernetes API access |
| Retained appliance Tailscale clients | Appliance owner | Do not couple appliance access to Kubernetes or legacy service retirement |
| Cluster Cloudflare Tunnel and bootstrap credential | OpenTofu | Required before in-cluster app reconciliation |
| Public GitHub repository and Flux bootstrap | Manual bootstrap | Flux pulls over public HTTPS without a deploy key; Actions do not deploy |
| Talos image, machine configuration, bootstrap, and client configuration | `homelab` OpenTofu | Latest stable Sidero Labs provider; use write-only or ephemeral arguments where supported |
| Kubernetes platform and workloads | Flux | No second Kubernetes deployer |
| Per-app DNS, tunnel routes, Access, WAF, and rate limits | Crossplane HTTP resources | Home-hosted control plane; orphan on delete by default |
| Per-app Control D DNS rules | Crossplane HTTP resources | Direct managed resources |
| Pocket ID clients and groups | Crossplane HTTP resources | Credentials pushed to 1Password where supported |
| B2 buckets and keys | Crossplane HTTP resources | Never expose key material in Git or logs |
| Resend application keys | Crossplane HTTP resources | Application scoped |
| Fly Gatus app, Machine, and secrets | OpenTofu exception | Monitoring must remain outside the home failure domain |
| 1Password vault and service-account roots | Manual bootstrap | Prevent circular secret dependency |

`homelab` owns anything required to rebuild or reach a cluster while Kubernetes
is unavailable. OpenTofu owns that substrate and access infrastructure.
Crossplane owns only app-facing external APIs whose failure cannot prevent
cluster rebuild or recovery access. Do not add provider-opentofu during the
initial migration. Crossplane starts on `mbk` only, with raw provider-http
resources so API behaviour remains visible while learning. Introduce
compositions only after at least three resources share a stable schema and
lifecycle.

Every Crossplane managed resource defaults to orphan-on-delete. A resource may
be configured for external deletion only after its data classification,
recovery path, provider API behaviour, and cutover have been reviewed. HTTP
resources must use stable external identifiers, idempotency where the API
supports it, redacted observations, bounded timeouts, and explicit retryable
status codes.

### Repository boundaries

| Repository | End state |
| --- | --- |
| `kubelab` | Flux sources, Kubernetes platform controllers, workloads, app-scoped integrations, validation, and migration documentation |
| `homelab` | Cluster rebuild and recovery access, OpenTofu substrate, Talos lifecycle, appliances, and the Fly Gatus exception |
| `homelab-truenas` | Retired after all application ownership leaves TrueNAS Apps; retains only unavoidable NAS-local configuration if required |
| `homelab-docker` | Retired after Docker services migrate or receive an explicit appliance exception |
| `homelab-workflows` | Replaced by storage-local Kubernetes Jobs after RoMM workflows are proven |
| `homelab-fly` | Consolidated into the OpenTofu Fly exception or retained as its clearly bounded implementation |

Do not make broad cross-repository moves in one commit. Each ownership transfer
must identify the old owner, import or create the new resource, verify no drift,
switch consumers, and only then remove the old owner.

### Secret contract

Create a dedicated Kubernetes vault in 1Password as a manual root of trust:

- `mbk` receives a read/write service account because it must consume and
  create selected app credentials.
- `syd` receives a read-only service account.
- External Secrets Operator uses the 1Password SDK provider.
- Normal secret creation uses `PushSecret` with `IfNotExists` and
  `deletionPolicy: None`.
- Provider credentials, Talos secrets, break-glass material,
  database recovery credentials, and Cloudflare Tunnel tokens never enter Git,
  ordinary OpenTofu outputs, CI logs, or unencrypted plan artefacts.

The first secret delivery is deliberately manual. From a trusted workstation,
retrieve the cluster's 1Password service-account token and inject only the
bootstrap Kubernetes Secret after the API and CNI are healthy. ESO then owns
normal secret consumption. OpenTofu creates the Tailscale OAuth client and
Cloudflare Tunnel and stores their credentials in 1Password; ESO materialises
the Kubernetes Secrets; Flux reconciles the Tailscale operator and
`cloudflared`; and Crossplane may manage app routes only after the cluster
tunnel is healthy. Document the exact re-injection and rotation commands in
`homelab` recovery documentation before the first cutover.

Secret rotation must allow an overlap period where the provider permits it.
Changes that can replace or reveal credentials require a saved, reviewed
OpenTofu plan or an equivalent Crossplane dry-run/reconciliation review.

### Application metadata

Do not create a custom application catalogue, schema, generator, or operator.
Use ordinary Kubernetes objects as the source of truth. Apply the recommended
`app.kubernetes.io/*` labels to every workload and use each controller's
supported annotations where integration is required.

Commit explicit, readable resources. Do not use Kustomize `configMapGenerator`
or `secretGenerator`, generated manifests, templating scripts, or repository-
defined resource types. Kustomize may only compose upstream resources and
small cluster-specific patches. Helm values live directly in the upstream
Flux `HelmRelease` that consumes them; the Cilium bootstrap keeps one ordinary
Helm values file because networking must exist before Flux can run. Validation
must compare the bootstrap file with `.spec.values` in the Cilium
`HelmRelease`; a difference blocks bootstrap.

Homepage discovers local Services through its native Kubernetes integration
and `gethomepage.dev/*` annotations. Cross-cluster services and appliances are
plain, directly maintained Homepage configuration. Fly Gatus uses a plain,
directly maintained configuration in Git because it deliberately sits outside
both clusters. This small amount of duplication is preferable to maintaining a
custom metadata and generation layer while learning Kubernetes.

Crossplane resources are also direct provider-http managed resources. Do not
introduce custom XRDs or Compositions until repeated real resources demonstrate
a stable need for them.

## Supported Initial Version Set

Pin exact versions and digests in manifests and lock files; Renovate proposes
updates. The initial baseline is:

| Component | Initial version | Policy |
| --- | --- | --- |
| Talos Linux | `v1.13.8` | Latest stable; patch updates after the `syd` canary |
| Sidero Labs Talos provider | `0.11.0` | Latest stable; implemented in `homelab`, not this repository |
| Kubernetes | `v1.36.3` | Latest stable version in the approved Cilium pairing |
| Flux | `v2.9.4` | Pin bootstrap manifests |
| Gateway API CRDs | `v1.6.1` | Standard channel only; aligned with Cilium `v1.20.0` |
| Cilium | `v1.20.0` | Latest stable; lists Kubernetes 1.36 as e2e-tested |
| Traefik | chart `40.2.0`, app `v3.7.1` | Gateway API provider only |
| cert-manager | `v1.21.0` | Do not use the known-problematic disabled renewal policy |
| External Secrets Operator | `v2.6.0` | 1Password SDK provider and PushSecret |
| Crossplane | `v2.3.4` | Latest stable |
| provider-http | `v1.0.14` | Pin package digest where supported |
| Headlamp | chart/app `0.44.0` | One instance per cluster |
| CloudNativePG | operator `1.30.0` | Single instance by default |
| Tailscale | `v1.98.10` | Keep node extension and operator compatible |

Kubernetes `v1.36.3` and Cilium `v1.20.0` were approved together on 2026-08-15.
Cilium's stable compatibility matrix lists Kubernetes 1.36 as e2e-tested. Use
the newest stable upstream-tested combination rather than deliberately lagging
a minor release. Resolve every chart, container, provider, and tool to an exact
immutable version in its owning repository, and let Renovate propose the next
compatible update for review. Do not treat a successful installation of an
unlisted combination as compatibility proof.

## Repository Design

Keep the tree shallow and make cluster differences explicit:

```text
.
├── AGENTS.md
├── README.md
├── LICENSE
├── PLAN.md
├── mise.toml
├── renovate.json
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/validate.yaml
├── clusters/
│   ├── mbk/
│   │   ├── flux-system/
│   │   └── kustomization.yaml
│   └── syd/
│       ├── flux-system/
│       └── kustomization.yaml
├── platform/
│   ├── sources/
│   ├── crds/
│   ├── networking/
│   ├── secrets/
│   ├── storage/
│   ├── identity/
│   ├── observability/
│   └── crossplane/
├── apps/
│   ├── base/
│   └── overlays/
│       ├── mbk/
│       └── syd/
└── docs/
```

Use upstream Helm charts first. Use `bjw-s/app-template` for simple workloads
without a maintained chart. Use raw manifests for learning exercises,
operators, and cases where the abstraction would hide important Kubernetes
behaviour. All YAML files use `.yaml`.

Local tools are managed by Mise and include version-pinned `kubectl`, `flux`,
`helm`, `kustomize`, `trivy`, `kubeconform`, and Prek. Prefer direct tool
commands and standard configuration over repository-specific scripts.

Prek runs formatting, YAML validation, Kustomize renders, Kubernetes schema
validation, and secret scanning. GitHub Actions runs the same validation on
pull requests. It does not hold kubeconfigs or deploy to a cluster. Rare custom
image builds may use Actions, but normal deployment always occurs by Flux
pulling Git.

## Implementation Sequence

### Phase 0: Repository and safety foundation

1. Commit this plan alone.
2. Add the lean repository structure, Australian English conventions,
   AGPL-3.0 licence, README, Mise, Prek, Renovate, and validation workflow.
3. Inventory all current services and external resources from the existing
   repositories. Give each one an owner, target, dependencies, storage class,
   backup tier, visibility, and rollback path.
4. Verify CIDRs, DNS zones, TrueNAS version, OCI quota, ARM64 image support,
   container architecture support, and provider API access in `homelab`.
5. Archive the existing `homelab` implementation on a protected branch, then
   simplify its main branch to explicit OpenTofu stacks without changing live
   ownership or state during the repository cleanup. Use the reviewed
   `homelab` GCS prefix for the single substrate root and leave the existing
   `states/core` objects untouched throughout the transition.

Exit gate: validation is reproducible locally, the inventory has no unknown
service, state and secret boundaries are documented, and the independently
reviewed `homelab` plans show no unexplained infrastructure changes.

### Phase 1: Home Talos trial (`homelab` repository)

This phase is implemented and logged in `homelab`; its `PLAN.md` owns the exact
provider resources, VM procedure, Talos configuration, state layout, and
recovery operations. This repository holds no Talos machine configuration,
secrets, Image Factory schematic, or lifecycle commands.

The substrate hand-off must provide a healthy Kubernetes API, reviewed Pod and
Service CIDRs, kubeconfig and Talos recovery material in 1Password, LAN and
host-level Tailscale access, the stable node identity, confirmed install disk,
and a tested reboot path. It must also confirm that the selected Kubernetes and
Cilium versions satisfy the compatibility gate before machine configuration is
applied.

Exit gate: the VM can be rebooted and reconstructed from documented inputs;
`talosctl health`, node readiness, and a disposable Pod all succeed.

### Phase 2: Cilium, Flux, and platform bootstrap

Install the CNI before Flux because Talos uses `cni.name: none`. After Flux is
available, use health checks between the remaining layers:

1. Cilium/Hubble manually with Helm while retaining kube-proxy; verify Pod and
   Service networking.
2. Flux controllers and the public HTTPS Git source; let Flux adopt the existing
   Cilium release without replacing it. Do not create an unnecessary deploy key.
3. Gateway API CRDs and other separately managed CRDs.
4. cert-manager and Traefik.
5. Tailscale operator and Cloudflare Tunnel.
6. External Secrets Operator and the manually injected home 1Password bootstrap
   Secret.
7. Static TrueNAS NFS test storage; CSI evaluation follows separately.
8. Headlamp with OIDC and least-privilege access.
9. VictoriaMetrics/VictoriaLogs and Grafana, sized for a single-node homelab.
10. Crossplane and provider-http after the platform is observable.

Use Flux `dependsOn`, health checks, timeouts, and separate Kustomizations for
CRDs, controllers, configuration, and workloads. Do not put the entire cluster
behind one reconciliation object.

Exit gate: Flux recreates a disposable OpenSpeedTest deployment; private and
public HTTP paths, TLS, DNS, logs, metrics, secrets, and static NFS persistence
survive a reboot.

### Phase 3: Prove dynamic automation

1. Add Homepage discovery annotations and a direct Gatus endpoint for the
   disposable OpenSpeedTest workload.
2. Reconcile one low-risk external HTTP resource through Crossplane, starting
   with a DNS record or Pocket ID test client.
3. Verify orphan-on-delete by removing its claim without deleting the external
   resource.
4. Test provider errors, credential rotation, timeout behaviour, redaction,
   drift correction, and API outage recovery.
5. Evaluate `democratic-csi` in an isolated namespace. Test NFS and then iSCSI
   provisioning, expansion, snapshots, Retain deletion, node reboot, driver
   upgrade, and manual volume reattachment.
6. Adopt dynamic storage only if those tests pass. Otherwise keep static NFS
   and document iSCSI as deferred.

Exit gate: Homepage discovery and the direct Gatus probe work, Crossplane
cannot accidentally delete the test resource, and the selected storage path
has a demonstrated restore procedure.

### Phase 4: Build `syd` as the canary cluster

1. Add a Talos OCI custom image for `arm64` to `homelab` and validate it in a
   non-destructive OpenTofu plan.
2. Replace the empty HSP Ubuntu instance only after the home success gate and a
   final confirmation that no valued state remains; the Kubernetes cluster on
   that host is named `syd` and its Talos node is named `hsp`.
3. Provision the OCI network, NSG, 64 GiB boot volume, and Talos instance from
   the root `homelab` state. Keep resource identities stable with keyed
   `for_each` values.
4. Bootstrap Talos, Flux, Tailscale, Cloudflare Tunnel, read-only 1Password,
   local-path storage, Headlamp, and the smaller observability footprint.
5. Use `syd` as the first canary for Talos, Kubernetes, and platform upgrades.

Exit gate: `syd` is independently rebuildable and a private/public disposable
workload is reachable without home connectivity.

### Phase 5: Migrate workloads in dependency order

Use one migration pull request and one cutover record per workload group:

1. Stateless utilities: OpenSpeedTest and other low-risk HTTP tools.
2. Platform consumers: Homepage, Headlamp integrations, Beszel agents, and
   directly maintained Gatus probes.
3. Identity-dependent applications after Pocket ID clients are dual-owned and
   tested.
4. Small stateful applications using application-native export/import or
   CloudNativePG backups.
5. Media and library applications using retained TrueNAS datasets and static
   or dynamic NFS.
6. Pocket ID itself only after break-glass access, export/restore, and all OIDC
   clients have been exercised.
7. RoMM and its guarded library workflows; replace workflow runners with
   Kubernetes Jobs only after NFS-mounted execution proves equivalent
   atomicity, permissions, locking, performance, and safety checks against a
   disposable copy of the library.

For every workload:

1. Freeze or export the old application as appropriate.
2. Take a final ZFS snapshot and any application-native backup.
3. Deploy without changing the public route.
4. Validate data, OIDC, mail, object storage, health, metrics, logs, and
   backup/restore.
5. Switch DNS/tunnel routing and watch both user traffic and Gatus.
6. Keep the old deployment stopped but recoverable for the rollback window.
7. Remove its old owner only after the new deployment is authoritative.

The accepted migration risk means a backup is not a universal hard gate, but a
failed restore test or unexplained data difference stops that workload's
cutover.

### Phase 6: Preserve appliances and special workloads

- Keep TrueNAS focused on storage, snapshots, replication, and the Talos VM.
- Keep Hotdog as the ZFS backup receiver. Monitor it with Beszel and Gatus; do
  not install Kubernetes on 2 GB RAM.
- Keep netboot and Syncthing as appliances unless migration solves a concrete
  problem without weakening storage locality.
- Replace Dozzle for Kubernetes workloads with VictoriaLogs/Grafana and
  Headlamp. Retain a host log view only where containers remain outside
  Kubernetes.
- Deploy the Bazzite ComfyUI Quadlet as an optional Tailscale service. Jobs must
  tolerate the workstation being offline and keep inputs/outputs in B2,
  Syncthing, or an explicitly mounted share.

### Phase 7: Automate and retire old delivery paths

1. Evaluate the pinned `PjSalty/truenas` OpenTofu provider 2.x in `homelab`
   against the running TrueNAS version.
2. Import the trial VM only when plan output is drift-free. Add
   `prevent_destroy` and document replacement explicitly. If the provider
   cannot model the VM safely, keep the manual VM definition authoritative
   instead of forcing automation.
3. Remove obsolete GitHub deployment workflows, Doco-CD configuration,
   TrueNAS application definitions, and workflow runners only after their last
   consumer migrates.
4. Reduce the existing OpenTofu estate to the ownership table in this plan.
5. Archive retired repositories with a README pointing to the successor and
   final commit.

Exit gate: Flux is the only Kubernetes deployer, every external resource has
one owner, the old deployment paths have no consumers, and disaster recovery
does not depend on CI.

## Workload Accounting

The inventory maintained in Phase 0 must include, at minimum, every service in
the current OpenTofu, Docker, TrueNAS, Fly, and workflow repositories. The
following categories are explicit sanity checks:

- Identity and access: Pocket ID, Tailscale, Cloudflare Access, break-glass
  Kubernetes access.
- User interfaces: Homepage and per-cluster Headlamp.
- Monitoring: Fly Gatus, Beszel, metrics, logs, dashboards, and alerts.
- Data services: databases, Redis-compatible stores, B2 buckets, Resend keys,
  and 1Password items.
- Media/library services and all mounted datasets.
- RoMM and storage-local maintenance/import workflows.
- Network and utility services including OpenSpeedTest, Cloudflare Tunnel, and
  private DNS.
- Appliances: TrueNAS, Hotdog, netboot, Syncthing, UniFi, and Bazzite.

An application is not accounted for merely because its container manifest
exists. Its route, identity, secrets, data, backups, mail, object storage,
monitor, dashboard entry, resource limits, architecture support, old owner,
and rollback procedure must all be present.

Before a stateful workload enters its cutover pull request, extend its inventory
record with the source dataset and path, size, UID/GID, database and application
versions, snapshot policy, export method, target PVC and storage class, expected
downtime, and dated restore evidence. Keep this detail in workload-specific
cutover documentation rather than widening the summary table.

## External OpenTofu Safety Contract

These rules apply to the separate `homelab` repository. This repository must
not contain OpenTofu configuration, provider locks, plans, state, or IaC helper
tooling.

- Use remote GCS state with versioning and the `homelab` prefix for the single
  substrate root. Leave the legacy `states/core` prefix untouched until every
  ownership transfer and rollback window is complete; do not migrate it into
  the new prefix.
- Pin OpenTofu and every provider. Commit dependency lock files for every
  platform on which plans run.
- Use maps with durable semantic keys for `for_each`; never use list indexes as
  resource identity.
- Keep credentials out of resource arguments and state whenever provider APIs
  permit it. Marking a value sensitive only redacts output; it does not remove
  it from state.
- Avoid data sources whose volatile results cause identity churn. Persist image
  OCIDs and other selected identities as reviewed inputs.
- Add `prevent_destroy` to critical buckets, state foundations, retained VMs,
  and other irreplaceable resources. Do not use broad `ignore_changes` to hide
  drift.
- Save plans and inspect creates, updates, replacements, deletions, and
  sensitive values. Apply exactly the reviewed plan file.
- Run applies locally from a trusted workstation initially. GitHub Actions may
  validate OpenTofu but receives no broad cloud credentials and performs no
  apply.
- Backend or state moves are separate changes with a backup, migration plan,
  serial review, and rollback test.

## Backup and Recovery

Backup tiers are deliberately small:

| Tier | Local retention | Off-site retention | Examples |
| --- | --- | --- | --- |
| Critical | Daily TrueNAS snapshots for 7 days | Weekly ZFS replication to Hotdog for 4 weeks and selected weekly B2 export | identity, application databases, unique configuration |
| Important | Daily TrueNAS snapshots for 7 days | Weekly Hotdog replication for 4 weeks | media metadata and costly-to-rebuild state |
| Replaceable | None or short local snapshots | None | caches, `syd` local-path, downloaded artefacts |

Back up data, not ephemeral cluster state. Git contains desired state; 1Password
contains bootstrap secrets; TrueNAS/Hotdog/B2 contain valued data. Document and
exercise:

- complete `mbk` rebuild while retaining TrueNAS datasets;
- complete `syd` replacement;
- CloudNativePG restore to a new namespace;
- static/dynamic retained volume reattachment;
- Pocket ID restore plus break-glass authentication;
- Flux bootstrap when GitHub Actions is unavailable;
- recovery from an unwanted Crossplane external change;
- GCS OpenTofu state object rollback.

Run a quarterly restore exercise after migration. A successful backup job
without a restore test is not proof of recovery.

## Validation and Operations

Every pull request must pass local-equivalent validation:

- formatting and linting;
- Kustomize render for both clusters;
- Kubernetes schema validation against the pinned version and installed CRDs;
- Helm template rendering;
- Flux reconciliation graph checks;
- secret and credential scanning;
- ARM64 image availability for `syd` workloads;
- resource requests, limits, probes, Pod security context, and NetworkPolicy
  policy checks.

Renovate opens version updates for manual merge. Platform upgrades go to `syd`
first, soak for at least 48 hours with Gatus green, then proceed to home.
Talos, Kubernetes, Cilium, Gateway API, storage drivers, and CRDs are upgraded
in separate changes unless upstream requires a coupled version.

Operational checks after every reconciliation include Flux readiness, node
health, certificate expiry, tunnel health, Tailscale connectivity, storage
provisioning, backup freshness, Gatus status, and unexpected Crossplane drift.

## Immediate Implementation Order

After this plan-only commit:

1. Scaffold and validate the repository foundation.
2. Build the current-estate migration inventory in documentation and direct
   Kubernetes manifests.
3. Archive and simplify `homelab`, then move all OpenTofu and Talos lifecycle
   configuration there without changing live infrastructure ownership.
4. In `homelab`, review and create the TrueNAS bridge, DHCP reservation, trial
   VM, and Talos cluster after confirming the discovered install disk.
5. Bootstrap Flux and the home platform from this repository in dependency
   order.
6. Prove OpenSpeedTest, HTTP routes, secrets, static NFS, Homepage discovery,
   a direct Gatus probe, and one Crossplane HTTP resource.
7. Stop for a home success review before any `syd` reset.

No step may silently cross an ownership, deletion, credential, or destructive
boundary. When a better-supported component or materially simpler design is
found, update this plan and record the decision before implementing it.

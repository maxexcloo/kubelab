# Kubernetes Homelab Migration Plan

## Status

This document is the authoritative implementation plan for migrating the
homelab to Kubernetes. It replaces the disposable local-cluster plan.

The first implementation target is a single-node Talos cluster in a TrueNAS
virtual machine. That trial must prove installation, GitOps, networking,
storage, secrets, recovery, and one disposable workload before the existing
Sydney OCI host (`hsp`) is reset. No valued workload is removed until its
replacement passes the applicable migration gate.

Git history is the implementation log. Changes use small, imperative commits
that record one coherent outcome. This complete plan is the first commit and
contains no implementation files.

## Goals

- Learn Kubernetes, Talos, Flux, Helm, Gateway API, storage, policy, and
  day-two operations through the real homelab migration.
- Keep the clusters reproducible from Git plus documented bootstrap material.
- Prefer stock upstream components, official charts, and small configuration
  surfaces.
- Keep GitHub Actions optional: CI validates changes and may build uncommon
  images, but never deploys a cluster.
- Preserve private access through Tailscale and public HTTP access through
  Cloudflare Tunnel.
- Preserve 1Password secrets, Pocket ID OIDC, Resend mail, Backblaze B2 object
  storage, Fly-hosted monitoring, Homepage, backups, and existing appliances.
- Generate Homepage entries and Gatus probes from the same application
  metadata rather than maintaining independent lists.
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
| `au` | TrueNAS VM at home | 12 vCPU, 32 GB RAM, about 160 GB boot disk | Single-node Talos control plane and primary workloads | TrueNAS NFS/iSCSI plus local scratch |
| `au-oci` | OCI Sydney | Ampere A1, 2 OCPU, 12 GB RAM, 160 GB boot disk | Single-node Talos control plane and independent secondary workloads | Local-path, replaceable data only |
| `hotdog` | United States | Existing Linux host, 2 GB RAM | ZFS replication receiver and host-monitored appliance | Existing ZFS |
| `bazzite` | Home | Existing Bazzite workstation with AMD RX 6000 GPU | Opportunistic rootless Podman worker | Existing local storage |

Both Kubernetes clusters schedule workloads on their control-plane node. They
are deliberately independent; a WAN failure cannot break etcd quorum. The
home cluster shares a failure domain with TrueNAS compute and storage. This is
accepted for the initial design and is not described as high availability.

The Bazzite host uses rootless Podman Quadlets for opt-in jobs such as ComfyUI.
It communicates over Tailscale and is advertised to Homepage and monitoring,
but it is not joined to Kubernetes. The first ROCm trial is container-only and
must not change the Bazzite kernel or host GPU driver.

### Cluster networking

| Network | CIDR |
| --- | --- |
| `au` Pods | `10.100.0.0/22` |
| `au` Services | `10.100.4.0/22` |
| `au-oci` Pods | `10.100.8.0/22` |
| `au-oci` Services | `10.100.12.0/22` |

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
  `*.excloo.com` names.
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

Pocket ID remains the OIDC provider and ultimately runs in `au`. One
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
iSCSI only after confirming TrueNAS 25.10 API compatibility, Talos system
extensions, snapshot behaviour, retained-volume recovery, and upgrade health.
The experimental API-only drivers are not production defaults. Record that
decision before migrating a database.

`au-oci` uses local-path storage only for replaceable state, caches, and replicas of
data whose authority is elsewhere. It must not become the only copy of valued
data.

## Ownership and Configuration Contracts

### Control-plane ownership

| Concern | Authoritative owner | Notes |
| --- | --- | --- |
| OCI VCN, subnet, NSG, Talos image, and `au-oci` VM | OpenTofu | Separate state from app-facing resources; reviewed plan before apply |
| TrueNAS trial VM | Manual, then OpenTofu if import is drift-free | Protect imported VM from destruction |
| GCS state foundations | OpenTofu bootstrap state | Versioning, retention, least-privilege credentials |
| Tailscale ACLs, grants, tags, OAuth clients, bootstrap keys | OpenTofu | Cluster/node identity is substrate access |
| Cluster Cloudflare Tunnel and bootstrap credential | OpenTofu | Required before in-cluster app reconciliation |
| GitHub repository and Flux deploy key bootstrap | OpenTofu/manual bootstrap | Flux pulls; Actions do not deploy |
| Talos machine configuration and client configuration | This repository | Generated from committed non-secret patches; secrets stay outside Git |
| Kubernetes platform and workloads | Flux | No second Kubernetes deployer |
| Per-app DNS, tunnel routes, Access, WAF, and rate limits | Crossplane HTTP resources | Home-hosted control plane; orphan on delete by default |
| Per-app Control D DNS rules | Crossplane HTTP resources | Direct managed resources |
| Pocket ID clients and groups | Crossplane HTTP resources | Credentials pushed to 1Password where supported |
| B2 buckets and keys | Crossplane HTTP resources | Never expose key material in Git or logs |
| Resend application keys | Crossplane HTTP resources | Application scoped |
| Fly Gatus app, Machine, and secrets | OpenTofu exception | Monitoring must remain outside the home failure domain |
| 1Password vault and service-account roots | Manual bootstrap | Prevent circular secret dependency |

OpenTofu owns substrate infrastructure. Crossplane owns only app-facing
external APIs whose failure cannot prevent rebuilding the Kubernetes substrate.
Do not add provider-opentofu during the initial migration. Crossplane starts on
`au` only, with raw provider-http resources so API behaviour remains
visible while learning. Introduce compositions only after at least three
resources share a stable schema and lifecycle.

Every Crossplane managed resource defaults to orphan-on-delete. A resource may
be configured for external deletion only after its data classification,
recovery path, provider API behaviour, and cutover have been reviewed. HTTP
resources must use stable external identifiers, idempotency where the API
supports it, redacted observations, bounded timeouts, and explicit retryable
status codes.

### Repository boundaries

| Repository | End state |
| --- | --- |
| `kubelab` | Talos configuration, Flux sources, platform controllers, workloads, validation, and migration documentation |
| `homelab` | Reduced OpenTofu substrate, access foundations, appliances, and the Fly Gatus exception |
| `homelab-truenas` | Retired after all application ownership leaves TrueNAS Apps; retains only unavoidable NAS-local configuration if required |
| `homelab-docker` | Retired after Docker services migrate or receive an explicit appliance exception |
| `homelab-workflows` | Replaced by storage-local Kubernetes Jobs after RoMM workflows are proven |
| `homelab-fly` | Consolidated into the OpenTofu Fly exception or retained as its clearly bounded implementation |

Do not make broad cross-repository moves in one commit. Each ownership transfer
must identify the old owner, import or create the new resource, verify no drift,
switch consumers, and only then remove the old owner.

### Secret contract

Create a dedicated Kubernetes vault in 1Password as a manual root of trust:

- `au` receives a read/write service account because it must consume and
  create selected app credentials.
- `au-oci` receives a read-only service account.
- External Secrets Operator uses the 1Password SDK provider.
- Normal secret creation uses `PushSecret` with `IfNotExists` and
  `deletionPolicy: None`.
- Provider credentials, Talos secrets, Flux deploy keys, break-glass material,
  database recovery credentials, and Cloudflare Tunnel tokens never enter Git,
  OpenTofu outputs, CI logs, or unencrypted plan artefacts.

Secret rotation must allow an overlap period where the provider permits it.
Changes that can replace or reveal credentials require a saved, reviewed
OpenTofu plan or an equivalent Crossplane dry-run/reconciliation review.

### Application metadata

Do not create a custom application catalogue, schema, generator, or operator.
Use ordinary Kubernetes objects as the source of truth. Apply the recommended
`app.kubernetes.io/*` labels to every workload and use each controller's
supported annotations where integration is required.

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
| Talos Linux | `v1.13.8` | Latest stable; patch updates after `au-oci` canary |
| Kubernetes | `v1.36.3` | Latest stable; upgrade separately from Talos |
| Flux | `v2.9.4` | Pin bootstrap manifests |
| Gateway API CRDs | `v1.5.1` | Standard channel only |
| Cilium | `v1.19.6` | Keep kube-proxy initially; tested through Kubernetes 1.34 |
| Traefik | chart `40.2.0`, app `v3.7.1` | Gateway API provider only |
| cert-manager | `v1.21.0` | Do not use the known-problematic disabled renewal policy |
| External Secrets Operator | `v2.6.0` | 1Password SDK provider and PushSecret |
| Crossplane | `v2.3.4` | Latest stable |
| provider-http | `v1.0.14` | Pin package digest where supported |
| Headlamp | chart/app `0.44.0` | One instance per cluster |
| CloudNativePG | operator `1.30.0` | Single instance by default |
| Tailscale | `v1.98.10` | Keep node extension and operator compatible |

Before the first cluster bootstrap, resolve every chart, container, provider,
and tool to an immutable version in the repository. Do not silently substitute
a different version. Track the latest stable release of every component rather
than deliberately lagging a minor release for soak time. If the latest stable
components are not an upstream-tested combination, prove the combination in
the home trial or stop and update this plan before deployment.

## Repository Design

Keep the tree shallow and make cluster differences explicit:

```text
.
├── AGENTS.md
├── README.md
├── LICENSE
├── plan.md
├── mise.toml
├── .pre-commit-config.yaml
├── .github/
│   ├── renovate.json5
│   └── workflows/validate.yaml
├── talos/
│   ├── patches/
│   │   ├── common.yaml
│   │   ├── au-oci.yaml
│   │   └── au.yaml
│   └── README.md
├── clusters/
│   ├── au-oci/
│   │   ├── flux-system/
│   │   └── kustomization.yaml
│   └── au/
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
│       ├── au-oci/
│       └── au/
└── tofu/
    ├── bootstrap/
    ├── au-oci/
    └── truenas/
```

Use upstream Helm charts first. Use `bjw-s/app-template` for simple workloads
without a maintained chart. Use raw manifests for learning exercises,
operators, and cases where the abstraction would hide important Kubernetes
behaviour. All YAML files use `.yaml`.

Local tools are managed by Mise and include version-pinned `kubectl`,
`talosctl`, `flux`, `helm`, `kustomize`, `cilium`, `tofu`, `tflint`, `trivy`,
`kubeconform`, `yamllint`, and `pre-commit`/Prek-compatible hooks. Prefer direct
tool commands and standard configuration over repository-specific scripts.

Prek runs formatting, YAML validation, Kustomize renders, Kubernetes schema
validation, secret scanning, and OpenTofu format/validate. GitHub Actions runs
the same validation on pull requests. It
does not hold kubeconfigs or run Flux/Talos/OpenTofu apply. Rare custom image
builds may use Actions, but normal deployment always occurs by Flux pulling
Git.

## Implementation Sequence

### Phase 0: Repository and safety foundation

1. Commit this plan alone.
2. Add the lean repository structure, Australian English conventions,
   AGPL-3.0 licence, README, Mise, Prek, Renovate, and validation workflow.
3. Inventory all current services and external resources from the existing
   repositories. Give each one an owner, target, dependencies, storage class,
   backup tier, visibility, and rollback path.
4. Verify CIDRs, DNS zones, TrueNAS version, OCI quota, ARM64 image support,
   container architecture support, and provider API access.
5. Split new OpenTofu state by blast radius. Enable GCS object versioning and
   retention. Never migrate existing state with an unreviewed backend change.

Exit gate: validation is reproducible locally, the inventory has no unknown
service, state and secret boundaries are documented, and `tofu plan` shows no
unexplained changes to existing infrastructure.

### Phase 1: Home Talos trial

1. Create the TrueNAS VM manually with 12 vCPU, 32 GB RAM, about 160 GB boot
   disk, UEFI, and a stable UniFi DHCP reservation.
2. Build a Talos 1.13.8 Image Factory image with only required extensions:
   Tailscale plus storage modules proven necessary for NFS/iSCSI.
3. Generate Talos secrets outside Git. Commit only non-secret machine patches.
4. Confirm the install disk from maintenance mode; never assume `/dev/sda` or
   `/dev/vda`.
5. Install the single node, bootstrap etcd once, retrieve kubeconfig, and store
   recovery material in 1Password.
6. Verify reboot, API access by LAN and Tailscale, clock, DNS, node health,
   Kubernetes scheduling, and a Talos patch/upgrade dry run.

Exit gate: the VM can be rebooted and reconstructed from documented inputs;
`talosctl health`, node readiness, and a disposable Pod all succeed.

### Phase 2: Flux and platform bootstrap

Bootstrap in dependency order with Flux health checks between layers:

1. Flux controllers and Git deploy key.
2. Gateway API CRDs and other separately managed CRDs.
3. Cilium/Hubble while retaining kube-proxy.
4. cert-manager and Traefik.
5. Tailscale operator and Cloudflare Tunnel.
6. External Secrets Operator and the home 1Password service account.
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

### Phase 4: Build `au-oci` as the canary cluster

1. Add a Talos OCI custom image for `arm64` and validate it in a non-destructive
   OpenTofu plan.
2. Replace the empty HSP Ubuntu instance only after the home success gate and a
   final confirmation that no valued state remains; the Kubernetes cluster on
   that host is named `au-oci`.
3. Provision the OCI network, NSG, boot volume, and Talos instance from the `au-oci`
   state. Keep resource identities stable with keyed `for_each` values.
4. Bootstrap Talos, Flux, Tailscale, Cloudflare Tunnel, read-only 1Password,
   local-path storage, Headlamp, and the smaller observability footprint.
5. Use `au-oci` as the first canary for Talos, Kubernetes, and platform upgrades.

Exit gate: `au-oci` is independently rebuildable and a private/public disposable
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
   Kubernetes Jobs that mount storage locally and enforce the same safety
   checks.

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

1. Evaluate the pinned `PjSalty/truenas` OpenTofu provider 2.x against the
   running TrueNAS version.
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

## OpenTofu Safety Rules

- Use remote GCS state with versioning, retention, encryption, and separate
  prefixes for bootstrap, `au-oci`, TrueNAS, and unrelated existing infrastructure.
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
| Replaceable | None or short local snapshots | None | caches, `au-oci` local-path, downloaded artefacts |

Back up data, not ephemeral cluster state. Git contains desired state; 1Password
contains bootstrap secrets; TrueNAS/Hotdog/B2 contain valued data. Document and
exercise:

- complete `au` rebuild while retaining TrueNAS datasets;
- complete `au-oci` replacement;
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
- OpenTofu format, validate, lint, security scan, and speculative plan where
  credentials are intentionally available;
- ARM64 image availability for `au-oci` workloads;
- resource requests, limits, probes, Pod security context, and NetworkPolicy
  policy checks.

Renovate opens version updates for manual merge. Platform upgrades go to `au-oci`
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
3. Add safe OpenTofu state and `au-oci` plans without applying them.
4. Add Talos patches and generate a reviewed home Image Factory schematic.
5. Create and bootstrap the manual TrueNAS trial VM.
6. Bootstrap Flux and the home platform in dependency order.
7. Prove OpenSpeedTest, HTTP routes, secrets, static NFS, Homepage discovery,
   a direct Gatus probe, and one Crossplane HTTP resource.
8. Stop for a home success review before any `au-oci` reset.

No step may silently cross an ownership, deletion, credential, or destructive
boundary. When a better-supported component or materially simpler design is
found, update this plan and record the decision before implementing it.

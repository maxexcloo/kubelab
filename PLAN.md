# Migration Plan

Authoritative roadmap, workload ownership, and cutover gates for remaining
migrations to `kubelab`. Substrate implementation details live in `homelab`.

## Architecture & Failure Domains

| Cluster | Location               | Node   | Role                                       | Storage                                 |
| ------- | ---------------------- | ------ | ------------------------------------------ | --------------------------------------- |
| `mbk`   | Home (TrueNAS VM)      | `taco` | Primary workloads and control plane        | Local-path scratch and TrueNAS NVMe NFS |
| `syd`   | OCI Sydney (Ampere A1) | `hsp`  | Independent canary and secondary workloads | Local-path, replaceable state only      |

### Retained Appliances

- **`hotdog`**: Linux/ZFS backup receiver (2 GB RAM) in the US. Receives ZFS replication; no Talos.
- **`mandu`**: Bazzite workstation with AMD GPU. Runs rootless Podman Quadlets over Tailscale; optional GPU worker.
- **`haos`**: Home Assistant OS appliance (ESPHome, ESPresense, Matter, Zigbee2MQTT). A suspended `mbk` Gateway API integration stages its public webhook-only route without exposing the user interface.
- **`netboot` / `syncthing`**: Storage-local TrueNAS appliances.
- **`gatus`**: Fly.io external uptime monitor outside the home failure domain.

## Ownership & Safety Contracts

- **Implementation Simplicity**: Keep migrations as clean and stock as possible. Use upstream defaults unless a current requirement or demonstrated incompatibility requires otherwise. Prefer official charts and standard Kubernetes resources; avoid speculative abstractions, custom automation, premature hardening, and future-proofing. Accept small, explicit repetition when it is clearer than introducing a framework.
- **Substrate vs Workloads**: `homelab` (OpenTofu) owns everything required to reach or rebuild a cluster (VM, compute, OCI, Tailscale host extension, Cloudflare Tunnel credentials). `kubelab` (Flux) owns all in-cluster workloads and app-scoped integrations.
- **Secret Contract**: 1Password is the root of trust. `homelab` owns cluster vaults and provisions each cluster's vault-scoped 1Password Connect credentials; `kubelab` owns their bootstrap delivery into Kubernetes, the in-cluster Connect deployment, workload credential definitions, generation, and delivery. External Secrets Operator uses the local Connect service to materialise cluster Secrets. Zero secrets in Git.
- **Secret Automation**: Every workload credential is generated or obtained by its declarative owner and written to 1Password automatically before delivery to the workload. Only cluster bootstrap credentials require operator-provided secret material; no workload may depend on a manually created 1Password item.
- **Secret Renames**: Treat a cluster-vault item title as an interface because External Secrets and recovery scripts resolve it by title. For a cross-repository rename, suspend the workload-item reconciler, apply the substrate-owned title change, reconcile every title-based consumer, then resume the reconciler and verify it is idempotent. Retain materialised Kubernetes Secrets throughout the transition.
- **Workload Items**: Use one display-named 1Password item per workload. The cluster vault carries scope; tag Kubernetes-created items only with `Kubelab`. Discover credential ownership and fields from External Secrets and Push Secrets, and discover browser-facing display names and websites from Homepage-labelled Gateway API routes. Treat a browser-facing HTTPRoute as an item source in its own right so it produces a Login item even without an External Secret or Push Secret; do not create route-only items for agent, API, callback, health, or other non-UI endpoints. Present every routed browser interface as a Login item and every unrouted credential-backed workload as a Server item. Preserve non-empty values edited in 1Password, generate only declared internal credentials, and archive Kubernetes-owned items with no remaining declarative consumer only while the cluster `apps` reconciliation is ready and has applied the current Git source revision. Keep the steady-state annotation contract to constants, defaults, and generated fields. Explicit adoption, field migration, and removal annotations are migration-only escape hatches. Copy migrated values while old deployments remain recoverable; remove adoption and migration annotations after live convergence, and remove legacy source fields only after the rollback window and previous delivery retirement. Use native username and password fields only for functional browser logins. Name custom fields by grouping first and sort them by major group, with `database-*` before `api-key-*`, credential usernames before their passwords, then labels alphabetically.
- **Purposeful APIs**: Repository-defined resources are acceptable when one small, workload-owned declaration replaces repeated integration logic and centralises security or lifecycle behaviour. Keep their scope narrow and use standard composed resources underneath.
- **Application DNS**: ExternalDNS owns explicitly labelled application records from Gateway API routes. OpenTofu owns cluster tunnel and direct-public targets. ExternalDNS adopts existing application records during cutover and uses upsert-only reconciliation.
- **Crossplane Resources**: Crossplane `provider-http` on `mbk` owns compatible app-scoped external APIs (B2 inventory, Cloudflare app policy, Pocket ID clients, and Resend keys). Every managed resource defaults to **orphan-on-delete**. Legacy Control D rules targeted previous Tailscale hosts and retire with those routes; current cluster wildcard DNS replaces them.
- **Storage Contract**: Both clusters use node-local `local-path` volumes only for replaceable state. `mbk` uses the `truenas-nfs` storage class backed by the cluster-scoped `truenas-nvme/clusters/mbk` NFS export for general retained data. Existing standalone datasets use allow-listed exports and retained static volumes. Databases run on CloudNativePG unless an official chart provides a simpler supported model; durable high-performance block storage requires a separately reviewed CSI evaluation.

## Cluster Bootstrap

After `homelab` has provisioned the substrate and bootstrapped Talos, initialise
the Kubernetes layer from this repository with:

```shell
mise run bootstrap syd
```

`bootstrap` must be idempotent and safely resumable. Its task dependency graph
must enforce this order:

1. `bootstrap-cilium` validates that the explicit cluster parameter has a
   matching `clusters/<cluster>` entry and kubeconfig context, shows the context
   and API endpoint, and requires confirmation before changing the cluster. It
   derives the chart name, repository, version, and values from the committed
   Flux resources, installs Cilium when Flux does not yet manage it, preserves
   Flux ownership otherwise, and waits for the nodes to become ready.
2. `bootstrap-secrets` waits for `bootstrap-cilium`, but does not depend on it.
   It reads controller credentials from the `Homelab` vault and applies the
   bootstrap Secrets without storing secret values in Git or files outside a
   restrictive temporary file. 1Password Connect is required on every cluster;
   optional controller credentials are discovered from the cluster overlay.
3. `bootstrap-flux` waits for `bootstrap-secrets`, but does not depend on it. It
   applies `clusters/<cluster>/flux-system` server-side, waits for the Flux
   controllers, starts reconciliation, and reports status. Flux then installs
   pinned upstream APIs and their controllers through the foundation stage.
4. `bootstrap` depends on all three component tasks and forwards the explicit
   cluster parameter to each one. Mise schedules them as one bootstrap operation
   while their `wait_for` relationships enforce Cilium, secrets, then Flux.

Keep the reviewed OpenTofu apply and Kubernetes bootstrap as separate operator
actions. Do not invoke this workflow from OpenTofu, a provider provisioner, or a
`local-exec` hook. Keep every task and script within `kubelab`; bootstrap must
not invoke another repository. Do not duplicate chart versions in tasks,
scripts, or documentation.

## Cluster Reconciliation

After bootstrap, reconcile a cluster without rerunning bootstrap
components:

```shell
mise run deploy syd
```

`deploy` reconciles the selected cluster's root Flux Kustomization and its Git
source. Flux remains the sole routine deployer for Kubernetes resources.

Reconciliation follows `flux-system`, `foundation`, `platform`, optional
cluster automation, then applications. App-scoped API integrations that require
a restored application run after applications without blocking their rollout;
their own readiness remains an explicit activation gate. Foundation owns
namespaces and pinned upstream declarations for APIs and controllers required by
later stages, including Gateway API, cert-manager, External Secrets, 1Password
Connect, and local-path provisioning. Platform applies the cluster secret store
only after the External Secrets CRDs are healthy, then installs secret consumers
including VictoriaMetrics. Generated CRDs are managed through their pinned
upstream chart or source rather than copied into this repository.

Parent inventories with health waiting enabled treat a deliberately suspended
child Kustomization or Helm release as current. Active resources must still
report `Ready=True` for their observed generation. This permits fail-closed
staging without making healthy dependency inventories appear failed.

## Cutover Controls

- **Access Policy**: Cluster wildcard DNS always resolves to the corresponding Tailscale service IP. `Public` attaches to the dedicated tunnel or direct-public Gateway and opts into ExternalDNS; never repoint a cluster wildcard at a public target. `Internal` uses Tailscale through the private Gateway and wildcard DNS. `Private` has no application route. `None` has no network endpoint.
- **State Protection**: Critical state uses retained NFS or CloudNativePG, daily snapshots, off-site backup, and application-native export where available. CloudNativePG databases write daily logical exports to retained NFS; validate the shared backup and restore mechanism once rather than repeating a restore drill during every workload cutover. Important state uses retained NFS and the Important backup tier. Replaceable state is reproducible from Git, 1Password, or upstream sources.
- **Observability**: Every routed user interface receives a Homepage entry. Gatus remains an independent external monitor and is not a per-workload migration gate. Agents and backends are checked through their owning service.
- **Rollback Window**: Old deployments remain stopped but recoverable for 7 days. Rollback restores previous routing, the latest retained snapshot, and the final migration export. Previous configuration is removed only after new deployments are proven.

## Migration Phases

Phase 1 foundations are complete. Crossplane manages sending-only Resend keys
for present mail-capable workloads on `mbk`; B2 inventory and Cloudflare WAF
adoption are implemented behind suspended Flux inventories. Phase 2 has started
with Anisette and Redlib cut over on `syd`; Byparr runs on `mbk`. OpenSpeedTest
is reconciled on both clusters. Actual Budget, Beszel, Bichon, Bifrost,
CLIProxyAPI, and Comfy Control are cut over on `mbk`, Homepage is reconciled on
`mbk`, Beszel agents are reconciled on both clusters, BookOrbit is cut over,
and Shelfmark is reconciled.

### Progress States

Use these states for every workload so repository implementation is not
mistaken for a completed migration:

1. **Planned**: ownership, destination, dependencies, and cutover approach are
   agreed.
2. **Implemented**: declarative resources are present in `kubelab`; live
   reconciliation is not yet confirmed.
3. **Reconciled**: Flux and the workload report healthy on the destination
   cluster.
4. **Cut over**: production routing points to Kubernetes and live traffic has
   been observed through application or gateway logs.
5. **Verified**: the 7-day rollback window has completed without an unresolved
   regression.
6. **Previous removed**: the old deployment and obsolete delivery configuration
   have been removed.

| Workload      | Current State | Next Gate                                                            |
| ------------- | ------------- | -------------------------------------------------------------------- |
| Actual Budget | Cut over      | Complete the rollback window                                         |
| Anisette      | Reconciled    | Record cutover evidence and the rollback window                      |
| Beszel        | Cut over      | Complete the rollback window                                         |
| Bichon        | Cut over      | Complete the rollback window                                         |
| Bifrost       | Cut over      | Complete the rollback window and migrate its provider dependencies   |
| BookOrbit     | Cut over      | Complete the rollback window                                         |
| Byparr        | Reconciled    | Record cutover evidence and the rollback window                      |
| CLIProxyAPI   | Cut over      | Complete the rollback window                                         |
| Comfy Control | Cut over      | Complete the rollback window                                         |
| Homepage      | Reconciled    | Record cutover evidence                                              |
| Larapaper     | Cut over      | Complete the rollback window                                         |
| Linkwarden    | Cut over      | Complete the rollback window                                         |
| Miniflux      | Cut over      | Complete the rollback window                                         |
| OpenSpeedTest | Implemented   | Confirm reconciliation on both clusters and retire prior deployments |
| Papra         | Cut over      | Complete the rollback window                                         |
| Redlib        | Reconciled    | Record cutover evidence and the rollback window                      |
| Shelfmark     | Reconciled    | Record cutover evidence and the rollback window                      |

### Phase 1: Observability & Dynamic Automation

1. **Observability — Complete**: VictoriaMetrics, VictoriaLogs, and Grafana run on `mbk` and `syd` for cluster metrics and logs (replacing Dozzle).
2. **ExternalDNS Automation — Complete**: ExternalDNS runs on both clusters. Application records are opt-in, Cloudflare-scoped, adopt existing records during cutover, and are upsert-only.
3. **1Password Workload Items — Implemented**: Homepage-labelled HTTPRoutes seed Login items instead of only enriching items discovered through External Secrets or Push Secrets. Grafana and Headlamp carry Homepage metadata on both clusters; Grafana's functional administrator credentials come from its cluster vault, while Headlamp remains URL-only. The `mbk` Grafana overlay adopts the retained OIDC client fields and configures Pocket ID; `syd` retains local administrator access only. Unit tests cover repeat normalisation and prevent archival until the current applications revision is ready. The currently deployed predecessor is healthy and idempotent on both clusters; reconcile this revision and confirm the expanded item set converges before marking the work complete.
4. **Crossplane Automation — Implemented, External Policies Staged**: Crossplane and `provider-http` run on `mbk`. Resend uses one full-access bootstrap credential per cluster, named `Resend: <cluster>` in the `Homelab` vault, and separate sending-only workload keys. The narrow `PocketIDClient` contract composes standard provider-http Requests, adopts and updates restored clients without create or delete authority, and reconciles their group access. Pocket ID group Requests may create missing named groups but omit delete authority. The Pocket ID API declarations reconcile after applications with Flux health waiting disabled because the authority is deliberately suspended; every resource must still become Ready during private activation. Beszel's B2 Requests adopt and update bucket policy without create or delete authority and observe the existing one-time application key without rotation authority. `RedlibWAFPolicy` discovers the Cloudflare zone and updates the phase entry point while retaining every unrelated rule; its Flux inventory remains suspended because first activation changes live request handling. Bootstrap both least-privilege controller credentials with `mise run bootstrap-automation-secrets mbk`, then follow [`docs/external-automation.md`](docs/external-automation.md). All external resources remain orphan-on-delete. Add other app-scoped APIs with the workload that consumes them.
5. **Storage Evaluation — Trial Ready**: `democratic-csi` is unsuitable for TrueNAS 26 because its TrueNAS integration depends on the removed REST API or privileged SSH. Trial the official WebSocket-based TrueNAS CSI driver on `mbk`; retain NFS as the production default until provisioning, retention, snapshots, recovery, and upgrades pass. See [`docs/storage.md`](docs/storage.md).

OnePassword Connect and VictoriaMetrics move between the `platform` and
`foundation` Flux inventories in the current implementation. Their transferred
live objects carry migration-only `prune: disabled` annotations. Because
`foundation` reconciles first, it actively adopts OnePassword Connect before the
old platform inventory drops it. Each cluster's foundation overlay temporarily
includes only the pre-existing, cluster-patched VictoriaMetrics resources with
Flux's `IfNotPresent` apply policy while the new platform inventory adopts and
extends them. This prevents the old owner from reverting the new Grafana
credential contract and preserves fresh-cluster bootstrap ordering. After both
inventories apply this bridge revision, remove VictoriaMetrics from the
foundation overlays in a reviewed change. Remove the prune guards only after
that follow-up revision applies and the old inventories no longer report
ownership.

### Phase 2: Workload Migration (Dependency Order)

Execute migrations with one pull request and cutover record per workload group:

1. **Stateless Utilities — In Progress**: `anisette` and `redlib` are cut over on `syd`; `byparr` runs on `mbk`. Redlib's exact legacy defaults are restored, its monitoring token is adopted, and its Cloudflare JS-challenge policy is implemented in a suspended `mbk` automation inventory pending reviewed activation.
2. **Platform Consumers — Reconciled**: Homepage runs on `mbk` with native
   Gateway API discovery. It discovers `mbk` only; `syd` metadata remains on
   workload `HTTPRoute` objects until Homepage gains native multi-cluster
   discovery. Retained Gatus, HAOS, Netboot, Syncthing, TrueNAS, and UniFi
   interfaces use static entries with current substrate addresses. The Beszel hub runs privately on `mbk` with retained NFS data,
   and agents on both clusters connect through an agent-only public WebSocket
   route. Both interfaces have live cutover evidence.
3. **Identity-Dependent & Small Stateful — In Progress**: Actual Budget,
   Bichon, Bifrost, CLIProxyAPI, Comfy Control, Larapaper, and Papra are cut
   over on `mbk`.
4. **Databases & Media Libraries — In Progress**: Miniflux, Linkwarden, and
   BookOrbit are cut over; Shelfmark is reconciled.
   - CloudNativePG operator for PostgreSQL instances.
   - `miniflux` (Postgres).
   - `linkwarden` (Postgres + storage).
   - `bookorbit` & `shelfmark` (retained NFS libraries).
   - `romm` (Postgres + Redis/Valkey + NFS library).
5. **RoMM Workflows**: Storage-local Kubernetes Jobs mounting NFS (replacing previous GitHub Actions runners).
6. **Identity Authority (Pocket ID)**: Migrate last. Validate break-glass cluster-admin credentials and full export/restore before DNS cutover.

### Workload Cutover Checklist

For every stateful service:

1. Inspect the previous TrueNAS application and data through
   `ssh root@kimbap`; export application data and rely on the scheduled
   TrueNAS snapshot policy rather than creating a per-cutover snapshot.
2. Deploy workload in Kubernetes; verify database, OIDC, mail, and storage connectivity before changing routing.
3. Switch DNS / Cloudflare Tunnel route and observe live traffic in application or gateway logs.
4. Keep the previous container stopped for the rollback window (7 days).
5. Remove the previous definition from old repositories only after verification.

### Phase 3: Retirement of Previous Repositories

1. Retire obsolete GitHub Actions deployment workflows and Doco-CD configs.
2. Retire `homelab-truenas`, `homelab-docker`, and `homelab-workflows`.
3. Verify Flux is the sole deployer and disaster recovery does not depend on CI.

## Migration Inventory

### Kubernetes and Application Services

| Service                       | Current Owner                          | Destination                  | Strategy      | Access   | Data and Integrations                                                     |
| ----------------------------- | -------------------------------------- | ---------------------------- | ------------- | -------- | ------------------------------------------------------------------------- |
| Actual Budget                 | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical NFS data, Pocket ID                                              |
| AIO Metadata                  | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                               |
| AIOStreams                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                               |
| Anisette                      | `homelab-truenas`                      | `syd`                        | Migrate       | Public   | Replaceable local library data                                            |
| Beszel                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical data, B2, Pocket ID, Resend                                      |
| Beszel agents                 | `homelab` target repositories          | Cluster and appliance owners | Replace       | Private  | Flux owns cluster agents; retained appliances use native service          |
| Bichon                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical mail archive                                                     |
| Bifrost                       | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important configuration, CLIPROXYAPI and Comfy Control                    |
| BookOrbit                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical library, Pocket ID, Resend                                       |
| Byparr                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Stateless backend for Shelfmark                                           |
| CLIPROXYAPI                   | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Replaceable credentials and configuration, Bifrost                        |
| Cloudflared                   | `homelab-truenas`                      | Both clusters                | Replace       | Private  | Cluster-specific public ingress connector                                 |
| Comfy Control                 | `homelab-truenas`                      | `mbk` plus Mandu             | Replace       | Internal | Controller in Kubernetes; optional GPU worker on Mandu                    |
| Dozzle                        | `homelab-truenas`                      | None                         | Retire        | Internal | Replaced by VictoriaLogs, Grafana, and Headlamp                           |
| Dozzle agents                 | `homelab-docker`                       | None                         | Retire        | Private  | Remove after the last Docker workload leaves                              |
| Gatus                         | `homelab-fly`                          | Fly                          | Retain        | Internal | External failure domain, Tailscale, Resend, direct Git config             |
| GitHub runner                 | `homelab-truenas`                      | None                         | Retire        | None     | CI validates only; Flux deploys                                           |
| Grafana                       | `homelab-truenas`                      | `mbk`                        | Replace       | Internal | Platform observability, Pocket ID                                         |
| Homepage                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Native Kubernetes discovery plus direct appliance entries                 |
| Larapaper                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Important NFS data                                                        |
| Linkwarden                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and archive, Pocket ID, Resend                          |
| Miniflux                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical database, Pocket ID                                              |
| OAuth2 Proxy                  | `homelab-docker` and `homelab-truenas` | None                         | Retire        | None     | No consumer remains after Dozzle retirement and native OIDC adoption      |
| Open WebUI                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical application data, Pocket ID                                      |
| OpenSpeedTest                 | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace first | Internal | Disposable learning workload                                              |
| Papra                         | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical documents, Pocket ID                                             |
| Pocket ID                     | `homelab-truenas`                      | `mbk`                        | Migrate last  | Public   | Critical identity data, Resend, break-glass required                      |
| Redlib                        | `homelab-truenas`                      | `syd`                        | Migrate       | Public   | Stateless, Cloudflare policy                                              |
| RoMM                          | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and retained NFS library, Pocket ID                     |
| RoMM workflows                | `homelab-workflows`                    | `mbk` Jobs                   | Replace       | None     | Guarded storage-local Jobs; no Actions runner                             |
| Shelfmark                     | `homelab-truenas`                      | `mbk`                        | Replace       | Public   | Supported successor to Shelfarr; retains BookOrbit, Byparr, and Pocket ID |
| Tailscale Kubernetes operator | `homelab` and target repositories      | Both clusters                | Replace       | Private  | Flux-owned operator; OAuth client, tags, and policy stay in OpenTofu      |
| Traefik                       | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace       | Private  | Gateway API implementation for internal and public routes                 |
| VictoriaMetrics               | `homelab-truenas`                      | Both clusters                | Replace       | Internal | Replaceable platform metrics; home is primary                             |

### Retained Appliances and Substrate

| System                      | Current Owner     | Destination         | Strategy | Notes                                                                                            |
| --------------------------- | ----------------- | ------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| Appliance Tailscale clients | Appliance owners  | Retained appliances | Retain   | Preserve independently of Kubernetes operator and previous service retirement                    |
| HAOS                        | `homelab`         | HAOS appliance      | Retain   | Includes add-ons; suspended `mbk` route preserves only the public webhook path                   |
| Hotdog                      | `homelab`         | Hotdog              | Retain   | Linux/ZFS receiver on 2 GB RAM; do not install Talos                                             |
| Mandu                       | `homelab`         | Bazzite             | Retain   | Rootless Podman Quadlets; optional AMD GPU worker over Tailscale                                 |
| Netboot                     | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local unless migration solves a concrete problem                                    |
| Syncthing                   | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local; expose status to Homepage/Gatus directly                                     |
| Talos Tailscale extension   | `homelab`         | Both Talos nodes    | Replace  | Host-level recovery path baked into each cluster image; identity stays in cluster OpenTofu state |
| TrueNAS                     | `homelab`         | TrueNAS             | Retain   | Storage, snapshots, replication, and the Taco Talos VM                                           |
| UniFi                       | `homelab`         | UniFi appliance     | Retain   | DHCP reservation, routing, and network policy remain substrate                                   |

### External Ownership

| Resource Family                                 | Owner After Migration                       | Deletion Default                   |
| ----------------------------------------------- | ------------------------------------------- | ---------------------------------- |
| B2 app buckets and keys                         | Direct provider-http Requests               | Orphan; existing keys observe-only |
| Cloudflare app Access, WAF, and rate limits     | `kubelab` workload compositions             | Orphan                             |
| Cloudflare application DNS                      | ExternalDNS from labelled Gateway routes    | Upsert only                        |
| Cluster Cloudflare tunnels, targets, and tokens | OpenTofu                                    | Prevent accidental replacement     |
| Legacy Control D host rules                     | None after previous host routes retire      | Preserve until route retirement    |
| Fly Gatus app, Machine, and deployed secrets    | `homelab-fly` bounded exception             | Reviewed replacement only          |
| Global Tailscale ACLs/grants and tag owners     | Foundations OpenTofu                        | Reviewed saved plan only           |
| OCI network, image, NSG, and `hsp` VM           | OpenTofu                                    | Reviewed saved plan only           |
| Pocket ID app clients and groups                | `PocketIDClient` and provider-http Requests | Orphan                             |
| Resend keys for Kubernetes apps                 | Crossplane `ResendKey` composition          | Orphan                             |
| Retained Gatus Resend key                       | `homelab-fly` bounded exception             | Orphan until reviewed replacement  |
| Retained appliance Tailscale identities         | Appliance owner                             | Explicit appliance procedure       |
| Tailscale operator OAuth clients                | Cluster-specific OpenTofu                   | Reviewed saved plan only           |
| Talos-node Tailscale bootstrap identities       | Cluster-specific OpenTofu                   | Reviewed saved plan only           |

## Backup Tiers

| Tier            | Local Snapshot         | Off-site Retention                                     | Workloads                                         |
| --------------- | ---------------------- | ------------------------------------------------------ | ------------------------------------------------- |
| **Critical**    | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks) + weekly B2 export | Pocket ID, PostgreSQL databases, unique configs   |
| **Important**   | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks)                    | Media metadata, document archives                 |
| **Replaceable** | None or short local    | None                                                   | Build artefacts, caches, cluster metrics and logs |

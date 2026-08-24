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
- **`haos`**: Home Assistant OS appliance (ESPHome, ESPresense, Matter, Zigbee2MQTT).
- **`netboot` / `syncthing`**: Storage-local TrueNAS appliances.
- **`gatus`**: Fly.io external uptime monitor outside the home failure domain.

## Ownership & Safety Contracts

- **Implementation Simplicity**: Keep migrations as clean and stock as possible. Use upstream defaults unless a current requirement or demonstrated incompatibility requires otherwise. Prefer official charts and standard Kubernetes resources; avoid speculative abstractions, custom automation, premature hardening, and future-proofing. Accept small, explicit repetition when it is clearer than introducing a framework.
- **Substrate vs Workloads**: `homelab` (OpenTofu) owns everything required to reach or rebuild a cluster (VM, compute, OCI, Tailscale host extension, Cloudflare Tunnel credentials). `kubelab` (Flux) owns all in-cluster workloads and app-scoped integrations.
- **Secret Contract**: 1Password is the root of trust. `homelab` owns cluster vaults and bootstraps each cluster's vault-scoped 1Password Connect credentials; `kubelab` owns the in-cluster Connect deployment, workload credential definitions, generation, and delivery. External Secrets Operator uses the local Connect service to materialise cluster Secrets. Zero secrets in Git.
- **Application DNS**: ExternalDNS owns explicitly labelled application records from Gateway API routes. OpenTofu owns cluster tunnel and direct-public targets. ExternalDNS adopts existing application records during cutover and uses upsert-only reconciliation.
- **Crossplane Resources**: Crossplane `provider-http` on `mbk` owns compatible app-scoped external APIs (Pocket ID clients, Control D rules, B2 buckets, Resend keys). Every managed resource defaults to **orphan-on-delete**.
- **Storage Contract**: Both clusters use node-local `local-path` volumes only for replaceable state. `mbk` uses the `truenas-nfs` storage class backed by the cluster-scoped `truenas-nvme/clusters/mbk` NFS export for general retained data. Existing standalone datasets use allow-listed exports and retained static volumes. Databases run on CloudNativePG unless an official chart provides a simpler supported model; durable high-performance block storage requires a separately reviewed CSI evaluation.

## Cutover Controls

- **Access Policy**: Cluster wildcard DNS always resolves to the corresponding Tailscale service IP. `Public` attaches to the dedicated tunnel or direct-public Gateway and opts into ExternalDNS; never repoint a cluster wildcard at a public target. `Internal` uses Tailscale through the private Gateway and wildcard DNS. `Private` has no application route. `None` has no network endpoint.
- **State Protection**: Critical state uses retained NFS or CloudNativePG, daily snapshots, off-site backup, and application-native export where available. Important state uses retained NFS and the Important backup tier. Replaceable state is reproducible from Git, 1Password, or upstream sources.
- **Observability**: Every routed user interface receives a Homepage entry. Gatus remains an independent external monitor and is not a per-workload migration gate. Agents and backends are checked through their owning service.
- **Rollback Window**: Old deployments remain stopped but recoverable for 7 days. Rollback restores previous routing and the final pre-migration snapshot/export. Previous configuration is removed only after new deployments are proven.

## Migration Phases

Phase 1 foundations are complete. Crossplane remains installed without a
managed resource until a compatible app-scoped API is required. Phase 2 has
started with Anisette and Redlib on `syd`; Byparr runs on `mbk`. OpenSpeedTest
is implemented on both clusters. Actual Budget, Beszel, Bichon, Bifrost,
CLIProxyAPI, and Comfy Control are cut over on `mbk`, Homepage is reconciled on
`mbk`, Beszel agents are reconciled on both clusters, and Windmill is
implemented on `mbk`.

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
| Byparr        | Reconciled    | Record cutover evidence and the rollback window                      |
| CLIProxyAPI   | Cut over      | Complete the rollback window                                         |
| Comfy Control | Cut over      | Complete the rollback window                                         |
| Homepage      | Reconciled    | Record cutover evidence                                              |
| Larapaper     | Cut over      | Complete the rollback window                                         |
| OpenSpeedTest | Implemented   | Confirm reconciliation on both clusters and retire prior deployments |
| Papra         | Cut over      | Complete the rollback window                                         |
| Redlib        | Reconciled    | Record cutover evidence and the rollback window                      |
| Windmill      | Implemented   | Confirm reconciliation and backup coverage                           |

### Phase 1: Observability & Dynamic Automation

1. **Observability — Complete**: VictoriaMetrics, VictoriaLogs, and Grafana run on `mbk` and `syd` for cluster metrics and logs (replacing Dozzle).
2. **ExternalDNS Automation — Complete**: ExternalDNS runs on both clusters. Application records are opt-in, Cloudflare-scoped, adopt existing records during cutover, and are upsert-only.
3. **Crossplane Automation — Foundation Complete**: Crossplane and `provider-http` run on `mbk`. Keep the provider idle until a compatible low-risk app-scoped resource is required; default every future resource to orphan-on-delete.
4. **Storage Evaluation — Trial Ready**: `democratic-csi` is unsuitable for TrueNAS 26 because its TrueNAS integration depends on the removed REST API or privileged SSH. Trial the official WebSocket-based TrueNAS CSI driver on `mbk`; retain NFS as the production default until provisioning, retention, snapshots, recovery, and upgrades pass. See [`docs/storage.md`](docs/storage.md).

### Phase 2: Workload Migration (Dependency Order)

Execute migrations with one pull request and cutover record per workload group:

1. **Stateless Utilities — In Progress**: `anisette` and `redlib` run on `syd`; `byparr` runs on `mbk`.
2. **Platform Consumers — Reconciled**: Homepage runs on `mbk` with native
   Gateway API discovery. It discovers `mbk` only; `syd` metadata remains on
   workload `HTTPRoute` objects until Homepage gains native multi-cluster
   discovery. The Beszel hub runs privately on `mbk` with retained NFS data,
   and agents on both clusters connect through an agent-only public WebSocket
   route. Both interfaces have live cutover evidence.
3. **Identity-Dependent & Small Stateful — In Progress**: Actual Budget,
   Bichon, Bifrost, CLIProxyAPI, Comfy Control, Larapaper, and Papra are cut
   over on `mbk`.
4. **Databases & Media Libraries**:
   Migrate `miniflux` next.
   - CloudNativePG operator for PostgreSQL instances.
   - `miniflux` (Postgres).
   - `linkwarden` (Postgres + storage).
   - `bookorbit` & `shelfmark` (retained NFS libraries).
   - `immich` (Postgres + Redis/Valkey + ML + NFS photos).
   - `romm` (Postgres + Redis/Valkey + NFS library).
5. **RoMM Workflows**: Storage-local Kubernetes Jobs mounting NFS (replacing previous GitHub Actions runners).
6. **Identity Authority (Pocket ID)**: Migrate last. Validate break-glass cluster-admin credentials and full export/restore before DNS cutover.

### Workload Cutover Checklist

For every stateful service:

1. Inspect the previous TrueNAS application and data through
   `ssh root@kimbap`; export application data and take a final TrueNAS ZFS
   snapshot.
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

| Service                       | Current Owner                          | Destination                  | Strategy      | Access   | Data and Integrations                                                |
| ----------------------------- | -------------------------------------- | ---------------------------- | ------------- | -------- | -------------------------------------------------------------------- |
| Actual Budget                 | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical NFS data, Pocket ID                                         |
| AIO Metadata                  | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                          |
| AIOStreams                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                          |
| Anisette                      | `homelab-truenas`                      | `syd`                        | Migrate       | Public   | Replaceable local library data                                       |
| Beszel                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical data, B2, Pocket ID, Resend                                 |
| Beszel agents                 | `homelab` target repositories          | Cluster and appliance owners | Replace       | Private  | Flux owns cluster agents; retained appliances use native service     |
| Bichon                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical mail archive                                                |
| Bifrost                       | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important configuration, CLIPROXYAPI and Comfy Control               |
| BookOrbit                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical library, Pocket ID, Resend                                  |
| Byparr                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Stateless backend for Shelfmark                                      |
| CLIPROXYAPI                   | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Replaceable credentials and configuration, Bifrost                   |
| Cloudflared                   | `homelab-truenas`                      | Both clusters                | Replace       | Private  | Cluster-specific public ingress connector                            |
| Comfy Control                 | `homelab-truenas`                      | `mbk` plus Mandu             | Replace       | Internal | Controller in Kubernetes; optional GPU worker on Mandu               |
| Dozzle                        | `homelab-truenas`                      | None                         | Retire        | Internal | Replaced by VictoriaLogs, Grafana, and Headlamp                      |
| Dozzle agents                 | `homelab-docker`                       | None                         | Retire        | Private  | Remove after the last Docker workload leaves                         |
| Gatus                         | `homelab-fly`                          | Fly                          | Retain        | Internal | External failure domain, Tailscale, Resend, direct Git config        |
| GitHub runner                 | `homelab-truenas`                      | None                         | Retire        | None     | CI validates only; Flux deploys                                      |
| Grafana                       | `homelab-truenas`                      | `mbk`                        | Replace       | Internal | Platform observability, Pocket ID                                    |
| Homepage                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Native Kubernetes discovery plus direct appliance entries            |
| Immich                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical photos and database, Pocket ID, Resend                      |
| Larapaper                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Important NFS data                                                   |
| Linkwarden                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and archive, Pocket ID, Resend                     |
| Miniflux                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical database, Pocket ID                                         |
| OAuth2 Proxy                  | `homelab-docker` and `homelab-truenas` | Both clusters if required    | Review        | Internal | Retain only for apps without direct OIDC or Access support           |
| Open WebUI                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical application data, Pocket ID                                 |
| OpenSpeedTest                 | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace first | Internal | Disposable learning workload                                         |
| Papra                         | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical documents, Pocket ID                                        |
| Pocket ID                     | `homelab-truenas`                      | `mbk`                        | Migrate last  | Public   | Critical identity data, Resend, break-glass required                 |
| Redlib                        | `homelab-truenas`                      | `syd`                        | Migrate       | Public   | Stateless, Cloudflare policy                                         |
| RoMM                          | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and retained NFS library, Pocket ID                |
| RoMM workflows                | `homelab-workflows`                    | `mbk` Jobs                   | Replace       | None     | Guarded storage-local Jobs; no Actions runner                        |
| Shelfmark                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Important data, BookOrbit and Byparr dependencies, Pocket ID         |
| Tailscale Kubernetes operator | `homelab` and target repositories      | Both clusters                | Replace       | Private  | Flux-owned operator; OAuth client, tags, and policy stay in OpenTofu |
| Traefik                       | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace       | Private  | Gateway API implementation for internal and public routes            |
| VictoriaMetrics               | `homelab-truenas`                      | Both clusters                | Replace       | Internal | Replaceable platform metrics; home is primary                        |
| Windmill                      | None                                   | `mbk`                        | Deploy        | Internal | Critical PostgreSQL data on retained NFS                             |

### Retained Appliances and Substrate

| System                      | Current Owner     | Destination         | Strategy | Notes                                                                                            |
| --------------------------- | ----------------- | ------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| Appliance Tailscale clients | Appliance owners  | Retained appliances | Retain   | Preserve independently of Kubernetes operator and previous service retirement                    |
| HAOS                        | `homelab`         | HAOS appliance      | Retain   | Includes ESPHome, ESPresense, Matter Hub, Studio Code Server, and Zigbee2MQTT                    |
| Hotdog                      | `homelab`         | Hotdog              | Retain   | Linux/ZFS receiver on 2 GB RAM; do not install Talos                                             |
| Mandu                       | `homelab`         | Bazzite             | Retain   | Rootless Podman Quadlets; optional AMD GPU worker over Tailscale                                 |
| Netboot                     | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local unless migration solves a concrete problem                                    |
| Syncthing                   | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local; expose status to Homepage/Gatus directly                                     |
| Talos Tailscale extension   | `homelab`         | Both Talos nodes    | Replace  | Host-level recovery path baked into each cluster image; identity stays in cluster OpenTofu state |
| TrueNAS                     | `homelab`         | TrueNAS             | Retain   | Storage, snapshots, replication, and the Taco Talos VM                                           |
| UniFi                       | `homelab`         | UniFi appliance     | Retain   | DHCP reservation, routing, and network policy remain substrate                                   |

### External Ownership

| Resource Family                                 | Owner After Migration                     | Deletion Default               |
| ----------------------------------------------- | ----------------------------------------- | ------------------------------ |
| B2 app buckets and keys                         | Direct Crossplane provider-http resources | Orphan                         |
| Cloudflare app Access, WAF, and rate limits     | `kubelab` workload integration            | Orphan                         |
| Cloudflare application DNS                      | ExternalDNS from labelled Gateway routes  | Upsert only                    |
| Cluster Cloudflare tunnels, targets, and tokens | OpenTofu                                  | Prevent accidental replacement |
| Control D app rules                             | Direct Crossplane provider-http resources | Orphan                         |
| Fly Gatus app, Machine, and secrets             | OpenTofu exception                        | Reviewed replacement only      |
| Global Tailscale ACLs/grants and tag owners     | Foundations OpenTofu                      | Reviewed saved plan only       |
| OCI network, image, NSG, and `hsp` VM           | OpenTofu                                  | Reviewed saved plan only       |
| Pocket ID app clients and groups                | Direct Crossplane provider-http resources | Orphan                         |
| Resend app keys                                 | Direct Crossplane provider-http resources | Orphan                         |
| Retained appliance Tailscale identities         | Appliance owner                           | Explicit appliance procedure   |
| Tailscale operator OAuth clients                | Cluster-specific OpenTofu                 | Reviewed saved plan only       |
| Talos-node Tailscale bootstrap identities       | Cluster-specific OpenTofu                 | Reviewed saved plan only       |

## Backup Tiers

| Tier            | Local Snapshot         | Off-site Retention                                     | Workloads                                         |
| --------------- | ---------------------- | ------------------------------------------------------ | ------------------------------------------------- |
| **Critical**    | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks) + weekly B2 export | Pocket ID, PostgreSQL databases, unique configs   |
| **Important**   | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks)                    | Media metadata, document archives                 |
| **Replaceable** | None or short local    | None                                                   | Build artefacts, caches, cluster metrics and logs |

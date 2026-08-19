# Migration Plan

Authoritative roadmap, workload ownership, and cutover gates for remaining
migrations to `kubelab`. Substrate implementation details live in `homelab`.

## Architecture & Failure Domains

| Cluster | Location               | Node   | Role                                       | Storage                                            |
| ------- | ---------------------- | ------ | ------------------------------------------ | -------------------------------------------------- |
| `mbk`   | Home (TrueNAS VM)      | `taco` | Primary workloads and control plane        | TrueNAS NVMe NFS (`truenas-nfs`) and local scratch |
| `syd`   | OCI Sydney (Ampere A1) | `hsp`  | Independent canary and secondary workloads | Local-path, replaceable state only                 |

### Retained Appliances

- **`hotdog`**: Linux/ZFS backup receiver (2 GB RAM) in the US. Receives ZFS replication; no Talos.
- **`mandu`**: Bazzite workstation with AMD GPU. Runs rootless Podman Quadlets over Tailscale; optional GPU worker.
- **`haos`**: Home Assistant OS appliance (ESPHome, ESPresense, Matter, Zigbee2MQTT).
- **`netboot` / `syncthing`**: Storage-local TrueNAS appliances.
- **`gatus`**: Fly.io external uptime monitor outside the home failure domain.

## Ownership & Safety Contracts

- **Substrate vs Workloads**: `homelab` (OpenTofu) owns everything required to reach or rebuild a cluster (VM, compute, OCI, Tailscale host extension, Cloudflare Tunnel credentials). `kubelab` (Flux) owns all in-cluster workloads and app-scoped integrations.
- **Secret Contract**: 1Password is the root of trust. `mbk` uses a read/write service account; `syd` uses read-only. External Secrets Operator (1Password SDK) materialises cluster Secrets. Zero secrets in Git.
- **Crossplane Resources**: Crossplane `provider-http` on `mbk` owns app-scoped external APIs (Cloudflare DNS/routes, Pocket ID clients, Control D rules, B2 buckets, Resend keys). Every managed resource defaults to **orphan-on-delete**.
- **Storage Contract**: TrueNAS persistent volumes use `Retain`. Databases run on CloudNativePG unless an official chart provides a simpler supported model.

## Remaining Migration Phases

### Phase 1: Observability & Dynamic Automation

1. **Observability**: Deploy VictoriaMetrics, VictoriaLogs, and Grafana on `mbk` and `syd` for cluster metrics and logs (replacing Dozzle).
2. **Crossplane Automation**: Deploy Crossplane with `provider-http` on `mbk`. Reconcile one low-risk DNS or Pocket ID test resource with orphan-on-delete.
3. **Storage Evaluation**: Evaluate `democratic-csi` against TrueNAS 26.0 for dynamic NFS/iSCSI. If unproven or brittle, retain static NFS for dataset PersistentVolumes.

### Phase 2: Workload Migration (Dependency Order)

Execute migrations with one pull request and cutover record per workload group:

1. **Stateless Utilities**: `anisette`, `byparr`, `redlib`.
2. **Platform Consumers**: `homepage` (using native `gethomepage.dev/*` discovery), `beszel` hub on `mbk` and cluster agents.
3. **Identity-Dependent & Small Stateful**: `bifrost`, `cliproxyapi`, `comfy-control`, `bichon`, `actual-budget`, `papra`, `larapaper`.
4. **Databases & Media Libraries**:
   - CloudNativePG operator for PostgreSQL instances.
   - `miniflux` (Postgres).
   - `linkwarden` (Postgres + storage).
   - `bookorbit` & `shelfmark` (retained NFS libraries).
   - `immich` (Postgres + Redis/Valkey + ML + NFS photos).
   - `romm` (Postgres + Redis/Valkey + NFS library).
5. **RoMM Workflows**: Storage-local Kubernetes Jobs mounting NFS (replacing legacy GitHub Actions runners).
6. **Identity Authority (Pocket ID)**: Migrate last. Validate break-glass cluster-admin credentials and full export/restore before DNS cutover.

### Workload Cutover Checklist

For every stateful service:

1. Export application data and take a final TrueNAS ZFS snapshot.
2. Deploy workload in Kubernetes; verify database, OIDC, mail, and storage connectivity before changing routing.
3. Switch DNS / Cloudflare Tunnel route and monitor live traffic via Gatus and logs.
4. Keep legacy container stopped for the rollback window (7 days).
5. Remove legacy definition from old repositories only after verification.

### Phase 3: Retirement of Legacy Repositories

1. Retire obsolete GitHub Actions deployment workflows and Doco-CD configs.
2. Retire `homelab-truenas`, `homelab-docker`, and `homelab-workflows`.
3. Verify Flux is the sole deployer and disaster recovery does not depend on CI.

## Backup Tiers

| Tier            | Local Snapshot         | Off-site Retention                                     | Workloads                                       |
| --------------- | ---------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| **Critical**    | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks) + weekly B2 export | Pocket ID, PostgreSQL databases, unique configs |
| **Important**   | Daily TrueNAS (7 days) | Weekly Hotdog replication (4 weeks)                    | Media metadata, document archives               |
| **Replaceable** | None or short local    | None                                                   | Caches, `syd` local-path, build artefacts       |

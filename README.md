# Kubelab

Kubernetes resources reconciled by Flux for a two-cluster homelab. The separate
`homelab` repository owns the substrate required to rebuild or reach a cluster
while Kubernetes is unavailable.

This README is the operational reference for the current system. `PLAN.md`
contains only unfinished work.

## Architecture & Ownership

- **`homelab`** owns Talos machines, cluster networking, Cloudflare tunnel
  credentials, Tailscale host identities, OCI resources, TrueNAS datasets and
  cluster-scoped 1Password Connect credentials.
- **`kubelab`** owns in-cluster controllers, workloads, application routes,
  application DNS and app-scoped external integrations.

| Cluster | Node   | Location              | Role                                       | Storage                            |
| ------- | ------ | --------------------- | ------------------------------------------ | ---------------------------------- |
| `mbk`   | `taco` | Home, as a TrueNAS VM | Primary workloads and control plane        | Local-path and TrueNAS NVMe NFS    |
| `syd`   | `hsp`  | OCI Sydney            | Independent secondary workloads and canary | Local-path, replaceable state only |

The following systems intentionally remain outside Kubernetes:

- **Gatus** runs on Fly.io as an independent external monitor.
- **HAOS** remains a dedicated Home Assistant appliance.
- **Hotdog** receives off-site ZFS replication.
- **Mandu** remains a Bazzite workstation and optional GPU worker.
- **Netboot and Syncthing** remain storage-local TrueNAS applications.

## Repository Layout

- `apps/`: workload bases, integrations and cluster overlays.
- `clusters/`: Flux entry points for each cluster.
- `platform/`: controllers and shared cluster configuration.

## Operations

Tooling is pinned and managed through [Mise](https://mise.jdx.dev/):

```shell
mise trust
mise run setup
mise run check
```

| Task                           | Description                                            |
| ------------------------------ | ------------------------------------------------------ |
| `mise run bootstrap <cluster>` | Bootstrap Cilium, secrets and Flux in dependency order |
| `mise run check`               | Run schema, formatting, lint and repository checks     |
| `mise run deploy <cluster>`    | Reconcile a cluster from Git                           |
| `mise run fmt`                 | Format project files                                   |
| `mise run prek`                | Run every Git hook across the repository               |
| `mise run setup`               | Install tools and Git hooks                            |

### Bootstrap

After `homelab` provisions the substrate:

```shell
mise run bootstrap syd
```

The task requires a cluster name matching `clusters/<cluster>` and a kubeconfig
context. It shows the context and API endpoint before confirmation, then
installs Cilium, materialises the provisioned 1Password Connect credentials and
starts Flux. OpenTofu apply and Kubernetes bootstrap remain separate operator
actions.

### Reconciliation

Reconcile an existing cluster without rerunning bootstrap:

```shell
mise run deploy syd
```

Flux applies foundation APIs and controllers first, shared platform resources
second, optional automation third and applications last. Flux is the only
routine deployer; CI validates but does not deploy.

## Platform

| Area          | Implementation                                                            |
| ------------- | ------------------------------------------------------------------------- |
| Certificates  | cert-manager with Cloudflare DNS-01 ACME                                  |
| GitOps        | Flux                                                                      |
| Management    | Headlamp and Homepage                                                     |
| Networking    | Cilium, Cloudflared, ExternalDNS and Traefik Gateway API                  |
| Observability | Grafana, VictoriaLogs and VictoriaMetrics                                 |
| Secrets       | External Secrets Operator backed by cluster-local 1Password Connect       |
| Storage       | Local Path Provisioner and the `truenas-nfs` NFS subdirectory provisioner |

OnePassword Connect is owned only by the foundation inventory. VictoriaMetrics
is owned only by the platform inventory.

## Workloads

`mbk` runs Actual Budget, AIOMetadata, AIOStreams, Beszel, Beszel Agent, Bichon,
Bifrost, BookOrbit, Byparr, CLIProxyAPI, Comfy Control, Homepage, Immich,
Larapaper, Linkwarden, Miniflux, Open WebUI, OpenSpeedTest, Papra, Pocket ID,
RoMM, Shelfmark and Windmill.

`syd` runs Anisette, Beszel Agent, OpenSpeedTest and Redlib.

Workload differences belong in `apps/overlays/<cluster>`; bases are not copied
between clusters.

## Networking & Ingress

Application routes and DNS records are workload-owned. `homelab` owns cluster
wildcards, tunnel credentials and stable tunnel or direct-public targets.

| Mode          | Gateway         | DNS target                    | Cloudflare proxy |
| ------------- | --------------- | ----------------------------- | ---------------- |
| Direct public | `public-direct` | `public.<cluster>.excloo.dev` | Per route        |
| Internal      | `private`       | Cluster Tailscale wildcard    | None             |
| Tunnel public | `public-tunnel` | `tunnel.<cluster>.excloo.dev` | Required         |

A public namespace and its `HTTPRoute` must carry
`gateway.excloo.dev/public-access: "true"`. Tunnel routes also set
`external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"`. ExternalDNS is
upsert-only, so route removal does not implicitly delete a DNS record. Private
routes are never discovered by ExternalDNS.

## Secrets & External Automation

1Password is the root of trust. Credentials, kubeconfigs and rendered Secret
values never enter Git. Each workload uses one display-named item in its cluster
vault; Kubernetes generates only declared internal credentials and preserves
non-empty operator-managed values.

Crossplane on `mbk` manages app-scoped provider APIs. Pocket ID clients and
groups and sending-only Resend keys are active. B2 inventory and the Redlib
Cloudflare WAF policy remain fail-closed behind suspended Flux inventories; the
steps required to resolve them are in `PLAN.md`.

App-scoped external resources default to orphan-on-delete. ExternalDNS is
upsert-only. Deleting a Kubernetes declaration must not delete an external
bucket, credential, identity client or unrelated WAF rule.

## Storage & Recovery

`kimbap` serves retained NFS storage at `10.4.0.3`. The `truenas-nfs` class
creates retained directories beneath `/mnt/truenas-nvme/clusters/mbk`.
Allow-listed standalone datasets use retained static volumes.

`taco` holds the active Kubernetes node-local volumes, including current
CloudNativePG database volumes. These are live production state, not legacy
copies. Critical database workloads write validated logical backups to retained
NFS. Replaceable caches, metrics and logs may remain node-local.

| Tier        | Local retention         | Off-site retention                             |
| ----------- | ----------------------- | ---------------------------------------------- |
| Critical    | Daily TrueNAS snapshots | Weekly Hotdog replication and weekly B2 export |
| Important   | Daily TrueNAS snapshots | Weekly Hotdog replication                      |
| Replaceable | None or short retention | None                                           |

Pocket ID has active database-backup and complete application-export schedules.
Its restore CronJob is intentionally suspended and manual: stop the active
authority, provide the exact retained archive path and SHA-256 digest, and
verify the encryption key before creating a restore Job.

RoMM has an active logical-backup schedule. Its storage-local workflow CronJob
is an intentionally suspended Job template. It serialises runs with an NFS lock
and fails closed for destructive modes; its outstanding activation decision is
recorded in `PLAN.md`.

### Current Rollback Window

The final workloads were cut over on 27 August 2026. Their stopped previous
applications and source copies remain on `kimbap`; no legacy container, rollback
archive or one-off cutover Job remains on `taco`.

- Pocket ID export: `/backup/pocket-id-final-20260827.zip`, SHA-256
  `aeffec66980a98f54be102efe02538f9edf2663cf08fe44a73162fcea8f83fd8`.
- RoMM dump: `/backup/romm-final-20260827.dump`, SHA-256
  `9053de9e22d743ac9f8c9568c685f458dcfb188120f5177615a46d1d256fbec0`.

Both archives are on NFS served by `kimbap`. Normal scheduled backups remain
active. The previous declarative implementation is preserved only as Git
history on `homelab` branch `archive/pre-kubernetes` at commit `1c9fc2a` and the
immutable `legacy` tag.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

# Live Migration Evidence

This record separates repository implementation from evidence observed on live
clusters. Update it after each reconciliation, rollback-window review, or
retirement action.

## Snapshot: 27 August 2026

### Cluster and ownership

- `mbk` applications and both clusters' foundation inventories applied revision
  `e6b160c30848f30595f2f5556325b533f4ac93d4`.
- `mbk` platform and Pocket ID automation applied revision
  `7922784f0b02254c307da74476e2e70eb3bc710a` before the later documentation and
  backup-only revisions.
- Both foundation inventories are Ready and contain no VictoriaMetrics or
  VictoriaLogs objects.
- Both platform inventories are Ready and own VictoriaMetrics. Both foundation
  inventories own OnePassword Connect. No old-owner inventory entries remain.
- The temporary foundation observability overlays are removed. Migration-only
  prune annotations remain pending explicit lifecycle approval.

### Stateful workload handoff

- AIOMetadata, AIOStreams, and Open WebUI were copied to their retained NFS
  targets with matching logical byte and file counts. Their old application
  containers are stopped and the Kubernetes releases are Ready.
- Pocket ID's legacy encryption key and the Kubernetes Secret have the same
  SHA-256 digest. The final application export is
  `/backup/pocket-id-final-20260827.zip`, with digest
  `aeffec66980a98f54be102efe02538f9edf2663cf08fe44a73162fcea8f83fd8`.
  The hash-gated restore Job imported it into CloudNativePG and successfully
  re-exported the restored authority.
- RoMM's final PostgreSQL dump is `/backup/romm-final-20260827.dump`, with
  digest `9053de9e22d743ac9f8c9568c685f458dcfb188120f5177615a46d1d256fbec0`.
  It restored 29 application tables. The retained configuration tree matches
  the staged NFS copy.
- The old Pocket ID and RoMM application writers are stopped. Their previous
  databases, files, definitions, and final migration archives remain intact for
  rollback.

### Routes and application health

- `aiometadata.excloo.com`, `aiostreams.excloo.com`, and `chat.excloo.com`
  resolve to the current `mbk` private Gateway at `100.109.10.13`. Their normal
  responses are 302, 200, and 200 respectively.
- `id.excloo.com` and `games.excloo.com` attach to the `public-tunnel` Gateway.
  Both routes report `Accepted=True` and `ResolvedRefs=True`; both public
  hostnames return 200 through Cloudflare.
- Pocket ID discovery and RoMM `/api/heartbeat` each return 200 directly through
  the new Gateway.
- All eleven retained `PocketIDClient` resources and all four group Requests
  report `Ready=True` and `Synced=True`.
- `*.syd.excloo.dev` now resolves to the current Tailscale Kubernetes proxy at
  `100.98.254.8`. Grafana, Headlamp, and OpenSpeedTest respond through the
  repaired private routes.

### Backups and suspended operations

- Manual Pocket ID database backup, Pocket ID application export, and RoMM
  database backup Jobs completed successfully. Each Job validates its own dump
  or ZIP before completion.
- The Pocket ID database and export schedules and the RoMM database schedule are
  active.
- Pocket ID restore and RoMM storage workflows remain suspended and manual.
  No disposable migration harness was added.

### Previous repository retirement

- `homelab` branch `archive/pre-kubernetes` is marked archived and inactive at
  commit `1c9fc2a`.
- The branch no longer presents setup, plan, or apply instructions. No GitHub
  workflow deploys it.
- Previous definitions and the immutable `legacy` tag remain available for
  rollback evidence. The live `homelab/main` worktree and state were not changed
  by this retirement commit.

## Open gates

### External automation credentials

The `B2 Automation: mbk` item is absent from the `Homelab` vault. Bootstrap
therefore stopped before creating any controller Secret. B2 adoption and the
Redlib Cloudflare WAF inventory remain suspended. Create the documented
least-privilege B2 and Cloudflare items before activation; do not reuse broader
credentials.

### Human identity checks

Complete the restored Pocket ID administrator passkey and mail checks and one
interactive OIDC login to RoMM during the rollback window. Automated discovery,
client, group, route, and application health checks are green.

### Rollback windows

The five final workload writers were stopped on 27 August 2026. Keep their old
containers, data, definitions, and migration archives recoverable for seven
full days. Do not remove them before 3 September 2026, and only remove them then
after confirming no unresolved regression.

Earlier cutovers retain their individual seven-day deadlines. A healthy
resource or successful request does not close a rollback window.

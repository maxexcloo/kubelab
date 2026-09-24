# Kubelab

Kubernetes workloads and app integrations reconciled by Flux. This README is
the operational reference; `AGENTS.md` contains repository conventions.

## Architecture & Ownership

| Cluster | Node   | Location           | Purpose                                    | Storage                            |
| ------- | ------ | ------------------ | ------------------------------------------ | ---------------------------------- |
| `mbk`   | `taco` | TrueNAS VM at home | Primary workloads                          | Local-path and TrueNAS NVMe NFS    |
| `syd`   | `hsp`  | OCI Sydney         | Independent secondary workloads and canary | Local-path; replaceable state only |

Both clusters have one node.

- **`homelab`** owns what is needed to rebuild or reach a cluster while Kubernetes
  is unavailable: Talos, cluster networking, tunnel credentials, Tailscale host
  identities, OCI resources, TrueNAS datasets and 1Password Connect credentials.
- **`kubelab`** owns in-cluster controllers, workloads, application routes and DNS,
  and app-scoped external integrations.

Gatus stays on Fly.io for independent monitoring. HAOS stays a dedicated
appliance with a `homelab`-owned webhook-only tunnel and DNS. Hotdog receives
off-site ZFS replication; Mandu is a Bazzite workstation and optional GPU worker.
Netboot and Syncthing remain storage-local TrueNAS applications.

## Repository Layout

- `apps/`: workload bases, external integration claims and cluster overlays.
- `clusters/`: Flux entry points and cluster-specific platform configuration.
- `platform/`: shared controllers, sources and automation contracts.

## Operations

Install the pinned tools and hooks through [Mise](https://mise.jdx.dev/):

```shell
mise trust
mise run setup
mise run check
```

| Command                                   | Purpose                                                                     |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `mise run bootstrap <cluster>`            | Install Cilium, bootstrap secrets and start Flux                            |
| `mise run check`                          | Validate manifests, metadata, formatting, scripts and secret reconciliation |
| `mise run deploy <cluster> [component]`   | Fetch Git and reconcile Flux entry points or a named stage                  |
| `mise run fmt`                            | Format project files                                                        |
| `mise run prek`                           | Run all Git hooks                                                           |
| `mise run setup`                          | Install tools and Git hooks                                                 |
| `mise run status <cluster> [application]` | Show reconciliation status or watch one app upgrade                         |

### Application Changes

Keep Helm releases and supporting resources in `apps/base/<application>` and
include them through `apps/overlays/<cluster>`. Keep differences in overlays;
do not copy application bases. Select each cluster's external automation in
`clusters/<cluster>/automation` and add claims only where needed.

### Bootstrap

After `homelab` provisions the substrate, run `mise run bootstrap syd` with a
matching kubeconfig context. The task confirms the context and API endpoint,
installs Cilium, injects the provisioned 1Password Connect credentials and token,
and starts Flux. Check progress with `mise run status syd`.

Connect credentials are the only secrets injected outside reconciliation.
OpenTofu apply and Kubernetes bootstrap are separate actions; routine upgrades
need neither.

### Reconciliation

Merge to `main`; Flux polls Git every minute. Use `mise run deploy mbk` to fetch
immediately. This waits for entry-point application, not whole-cluster health.
Each Helm release upgrades independently:

```shell
mise run status mbk miniflux
mise run status mbk
```

The optional application argument is its Helm release and namespace name.
Beszel Agent is a DaemonSet; inspect it with
`kubectl --context mbk -n beszel-agent rollout status daemonset/beszel-agent`.
Use `mise run deploy mbk apps` when you explicitly want to await all apps.

Readiness gates follow actual prerequisites:

1. Foundation installs the base APIs and controllers.
2. Platform waits for Crossplane and, on `mbk`, database and NFS controllers.
3. Crossplane runtime waits for the HTTP provider and composition function.
4. Automation waits for its generated CRDs.
5. Applications and external integration claims reconcile in parallel.

Monitoring, platform certificates and dashboards report their own health without
blocking unrelated upgrades. Identity, DNS and WAF claims retry until their own
namespace, credentials and API are available. The `apps` stage retains aggregate
workload health for status. Failed stages retry after 30 seconds; dependency
checks retry after five seconds.

Shared policy lives in `platform/bootstrap/flux-reconciliation`. Flux is the
routine deployer; CI only validates. Checks cover manifest schemas, service
metadata, secret reconciliation and focused external-API fixtures. Render changed
Helm charts separately; schema checks do not validate their generated workloads.

### Resources

CPU requests reserve scheduling capacity; CPU limits cap execution. Flux and
Crossplane can burst without CPU limits. Memory limits remain enabled;
Crossplane package runtimes request 128 MiB and allow 512 MiB.

Sydney uses smaller CPU requests for lightly loaded services to leave room for
rolling upgrades. Revisit these as sustained usage grows. Diagnose
`Insufficient cpu` using node allocations and pending Pod events; diagnose
`OOMKilled` using container memory usage and limits. VictoriaMetrics and kubelet
statistics provide utilisation data; `kubectl top` requires a Metrics API that
is not installed here.

### Upgrades

Use Renovate's GitHub Dependency Dashboard as the update queue and retry panel.
PRs are scheduled for Monday 00:00–07:00 Australia/Sydney. Non-major development
tooling updates are grouped, as are platform chart patch and digest updates.
Application upgrades, platform minor releases and major releases remain separate.
The dashboard can request updates outside the schedule; merges remain manual.

Review the PR, merge, then watch the affected application. Check release notes
and take the relevant backup before migrations: reverting an image does not
undo database changes.

## Platform & Workloads

| Area                | Implementation                                                               |
| ------------------- | ---------------------------------------------------------------------------- |
| Certificates        | cert-manager with Cloudflare DNS-01 ACME                                     |
| External automation | Crossplane with the HTTP provider and patch-and-transform function           |
| GitOps              | Flux                                                                         |
| Management          | Headlamp and Homepage                                                        |
| Networking          | Cilium, Cloudflared, ExternalDNS, Tailscale and Traefik Gateway API          |
| Observability       | Beszel for systems; Grafana, VictoriaLogs and VictoriaMetrics for Kubernetes |
| Secrets             | External Secrets backed by cluster-local 1Password Connect                   |
| Storage             | Local Path Provisioner and the `truenas-nfs` NFS subdirectory provisioner    |

`mbk` runs Actual Budget, AIOMetadata, AIOStreams, Beszel, Beszel Agent, Bichon,
Bifrost, BookOrbit, Byparr, CLIProxyAPI, Comfy Control, Homepage, Immich,
Larapaper, Linkwarden, Miniflux, Open WebUI, OpenSpeedTest, Papra, Pocket ID,
RoMM, Shelfmark and Windmill. `syd` runs Anisette, Beszel Agent, Homepage,
OpenSpeedTest and Redlib.

Companion caches, search services and Redlib's `ctrld` DNS proxy belong to their
apps. Stateful or migration-owning single replicas use recreate updates;
stateless Cloudflared uses rolling updates.

Homepage discovers its local cluster and adds shared external services and
bookmarks. Optional widget credentials come from the cluster's `Homepage` item;
missing values hide only that widget. It is served at `home.excloo.com` and
`homepage.mbk.excloo.dev` on `mbk`, and `homepage.syd.excloo.dev` on `syd`.

Beszel agents run on every node, retain their identity in host storage and
register by outbound WebSocket. The `mbk` agent uses the local hub Service;
`syd` uses its private HTTPS route. Use VictoriaMetrics for Pod metrics,
VictoriaLogs/Grafana for logs, and Headlamp or `kubectl` for live inspection.
Workload/Flux notification delivery is not configured.

## Networking & Ingress

Apps own their routes and DNS. `homelab` owns cluster wildcards, stable targets,
tunnel credentials and DNS for services outside Kubernetes.

| Mode          | Gateway         | DNS target                    | Cloudflare proxy |
| ------------- | --------------- | ----------------------------- | ---------------- |
| Direct public | `public-direct` | `public.<cluster>.excloo.dev` | Per route        |
| Internal      | `private`       | Cluster Tailscale wildcard    | None             |
| Tunnel public | `public-tunnel` | `tunnel.<cluster>.excloo.dev` | Required         |

Public namespaces and HTTPRoutes require `gateway.excloo.dev/public-access: "true"`.
Tunnel routes also require
`external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"`. Private routes are
excluded from public ExternalDNS discovery. Traefik redirects private and direct
HTTP to HTTPS; Cloudflare handles tunnel redirects.

Private vanity names use `PrivateDNSRecord`: Crossplane composes a DNS-only
Cloudflare CNAME through a dedicated ExternalDNS instance and a Control D spoof
rule to the cluster's Tailscale addresses. Both ExternalDNS instances mark records
`Kubelab ExternalDNS Managed`. The `homelab` wildcard remains the fallback.

`www.reddit.excloo.com` is DNS-only to Sydney's direct Gateway and redirects to
`reddit.excloo.com`. Its separate certificate isolates it from cluster wildcard
renewals. DNS-01 follows `homelab`'s CNAME delegation and uses public resolvers
for self-checks.

`scripts/render_service_inventory.sh` emits normalised route metadata as JSON;
`--include-static` adds Homepage's external monitored services.

## Secrets & External Automation

1Password is the root of trust. Each app uses a display-named item in its cluster
vault. Only declared internal credentials are generated; non-empty operator
values are preserved except fields explicitly declared as constants. Existing item
IDs, categories, tags, URLs and field order are preserved; duplicate titles stop
reconciliation. Credentials, kubeconfigs and rendered Secrets stay out of Git.
Application administrators use upstream setup flows; no job provisions accounts
through application APIs.

Crossplane runs on both clusters. `mbk` automates Pocket ID clients and groups,
sending-only Resend keys, and private Cloudflare/Control D DNS. `syd` automates
Redlib's `CloudflareWAFPolicy`. B2 is available on both and provisions Beszel's
bucket and key on `mbk`. Only selected integrations load provider credentials.

`homelab` owns the unqualified `Backblaze B2`, `Cloudflare WAF`, `Control D` and
`Resend` vault items tagged `Homelab`. External Secrets loads them into
`crossplane-system`. Generated app credentials are published only to their app
item and namespace.

The only repository-owned CronJob is `onepassword-items` (hourly at minute 17).
Its Python source lives beside the manifest in `platform/secrets/onepassword-items`.
Crossplane reconciles the integrations above continuously; Flux deploys resources
and External Secrets synchronises credentials. App settings without a supported
declarative interface are configured manually.

### B2 Storage Contract

`B2ObjectStorage` selects a bucket-name Secret, application-key name and 1Password
item. It creates or adopts a private encrypted bucket with a one-day hidden-file
lifecycle and a bucket-scoped read/write key. API endpoints are discovered at
authorisation. Claims cannot request account, bucket-management or key-management
permissions; duplicate or mismatched same-name keys block reconciliation.
The bucket-name Secret is input only. The endpoint and key are published to
`b2-application-key` in the app namespace and its 1Password item. Use one claim
per namespace. Restore an existing key from 1Password if its local Secret is lost;
B2 cannot return a previously issued secret key.

Beszel's `object-storage-*` fields live in its `Beszel` item. Configure backups
manually in Beszel's Backups screen; no job configures the app or runs its backups.

### Deletion & Recovery

Crossplane defaults to orphan-on-delete; ExternalDNS is upsert-only. Removing a
declaration retains its external bucket, key, identity client, DNS record or WAF
rule. Removing an app also leaves its 1Password item intact. Item archival and
external resource cleanup are manual; the reconciler never modifies `Homelab` items.

Pocket ID automation updates existing clients. Restore its database and the app
items containing client credentials before dependent workloads. Grafana keeps
separate local-admin and OIDC Secrets, with optional OIDC references at startup
for local recovery access.

## Storage & Recovery

`kimbap` serves NFS at `10.4.0.3`. The `truenas-nfs` class retains directories
under `/mnt/truenas-nvme/clusters/mbk`; allow-listed standalone datasets use
retained static volumes. `taco` holds active node-local volumes, including
CloudNativePG databases. Storage snapshots and off-site replication belong to
`homelab`; this repository does not schedule database backups or restores.
Existing `backup` PVCs and dumps are retained, but no longer refreshed. Recovery
of node-local databases must use an independently maintained backup or snapshot.

Bifrost 2 performs irreversible migrations. Before upgrading from Bifrost 1,
stop the app and back up its retained volume; follow the upstream
[migration guide](https://docs.getbifrost.ai/migration-guides/v2.0.0).

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

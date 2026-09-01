# Kubelab

Kubernetes resources reconciled by Flux for a two-cluster homelab. The separate
`homelab` repository owns the substrate required to rebuild or reach a cluster
while Kubernetes is unavailable.

This README is the operational reference for the current system.

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
- **HAOS** remains a dedicated Home Assistant appliance; `homelab` owns its
  webhook-only Cloudflare Tunnel route and DNS record.
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

| Task                                    | Description                                            |
| --------------------------------------- | ------------------------------------------------------ |
| `mise run bootstrap <cluster>`          | Bootstrap Cilium, secrets and Flux in dependency order |
| `mise run check`                        | Run schema, formatting, lint and repository checks     |
| `mise run deploy <cluster> [component]` | Reconcile a cluster or Flux component from Git         |
| `mise run fmt`                          | Format project files                                   |
| `mise run prek`                         | Run every Git hook across the repository               |
| `mise run setup`                        | Install tools and Git hooks                            |

### Bootstrap

After `homelab` provisions the substrate:

```shell
mise run bootstrap syd
```

The task requires a cluster name matching `clusters/<cluster>` and a kubeconfig
context. It shows the context and API endpoint before confirmation, then
installs Cilium, materialises the provisioned 1Password Connect credentials and
token, and starts Flux. These Connect values are the only secrets injected
outside reconciliation. External Secrets uses them to read the cluster vault;
OpenTofu apply and Kubernetes bootstrap remain separate operator actions.

### Reconciliation

Reconcile an existing cluster without rerunning bootstrap:

```shell
mise run deploy syd
```

Pass a Flux Kustomization name such as `apps` when only one reconciliation
component needs to be applied and awaited:

```shell
mise run deploy syd apps
```

Flux applies foundation APIs and controllers first, shared platform resources
second, the Crossplane package runtime third, external automation fourth and
applications last. The separate runtime stage lets a new cluster install the
Crossplane CRDs before applying the hardened package runtime configuration and
waits for the HTTP provider and composition function before automation starts.
Shared reconciliation policy lives in
`platform/bootstrap/flux-reconciliation`; cluster entry points contain only
cluster-specific stages and exceptional health checks. Flux is the only routine
deployer; CI validates but does not deploy.

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

`syd` runs Anisette, Beszel Agent, Homepage, OpenSpeedTest and Redlib.

Workload differences belong in `apps/overlays/<cluster>`; bases are not copied
between clusters.

Companion containers are limited to AIOMetadata's disposable Redis, Redlib's
app-scoped `ctrld` DNS proxy and RoMM's disposable Valkey; each owns a distinct
runtime service. Open WebUI's upstream chart uses its `copy-app-data` init
container to seed persistent application data. Stateful or migration-owning
single replicas use recreate updates, while stateless Cloudflared uses rolling
updates.

## Networking & Ingress

Application routes and DNS records are workload-owned. `homelab` owns cluster
wildcards, tunnel credentials, stable tunnel or direct-public targets and DNS
for external services and appliances such as Gatus and Home Assistant.

| Mode          | Gateway         | DNS target                    | Cloudflare proxy |
| ------------- | --------------- | ----------------------------- | ---------------- |
| Direct public | `public-direct` | `public.<cluster>.excloo.dev` | Per route        |
| Internal      | `private`       | Cluster Tailscale wildcard    | None             |
| Tunnel public | `public-tunnel` | `tunnel.<cluster>.excloo.dev` | Required         |

A public namespace and its `HTTPRoute` must carry
`gateway.excloo.dev/public-access: "true"`. Tunnel routes also set
`external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"`. ExternalDNS is
upsert-only, so route removal does not implicitly delete a DNS record. Private
routes are never discovered by the public ExternalDNS instance. Traefik
redirects direct-public and private HTTP requests to HTTPS; Cloudflare performs
the equivalent redirect for tunnel-public routes.

`www.reddit.excloo.com` is DNS-only to Sydney's direct Gateway and redirects to
the canonical `reddit.excloo.com` route. Its exact hostname uses a separate
certificate so its lifecycle cannot make either cluster wildcard certificate
unready. DNS-01 challenges follow the `homelab`-owned CNAME delegation and
cert-manager uses public recursive resolvers for self-checks.

Private `.excloo.com` vanity names use a namespaced `PrivateDNSRecord` contract.
Crossplane composes a DNS-only Cloudflare CNAME through a dedicated ExternalDNS
CRD source and a Control D spoof rule to the cluster Tailscale addresses. Both
external records are orphaned when the Kubernetes declaration is removed. The
public and private ExternalDNS instances mark Cloudflare records as
`Kubelab ExternalDNS Managed`. All declared private names, including
`beszel.excloo.com` and Homepage at `home.excloo.com`, are actively reconciled.
The substrate-owned `*.mbk.excloo.dev` wildcard remains the fallback for
private routes.

`scripts/render_service_inventory.sh` is the single normalised view of enabled
route metadata. It discovers clusters and supported route shapes dynamically,
emits stable JSON and can include Homepage's static monitored services with
`--include-static`.

## Secrets & External Automation

1Password is the root of trust. Credentials, kubeconfigs and rendered Secret
values never enter Git. Each workload uses one display-named item in its cluster
vault; Kubernetes generates only declared internal credentials and preserves
non-empty operator-managed values.

Crossplane is available on every cluster and manages app-scoped provider APIs.
The B2 application-storage contract is available on every cluster, with no
current workload claim. Pocket ID clients and groups, sending-only Resend keys
and private Cloudflare and Control D DNS are active on `mbk`. The generic
`CloudflareWAFPolicy` contract is active on `syd` through Redlib's app-scoped
claim, item and Secret.

Grafana's local administrator credential and retained Pocket ID client
credentials reconcile with the platform through separate Secrets. Its OIDC
environment references remain optional at startup so local recovery access
cannot block on Pocket ID or External Secrets. The retained client remains under
Pocket ID automation.

Application administrators are created through each application's upstream
setup flow. Generated login credentials remain in 1Password, but no in-cluster
job calls application APIs to create or modify accounts. Restored databases
retain their existing administrators.

`homelab` owns the `Backblaze B2`, `Cloudflare WAF`, `Control D` and `Resend`
items in each corresponding cluster vault. They are unqualified and tagged
`Homelab` so the cluster can read them while the application-item reconciler
leaves them alone. External Secrets materialises their provider credentials in
`crossplane-system`; no provider credential has a separate bootstrap path. The
only out-of-band secret injection is the cluster's 1Password Connect
credentials and token. Generated application credentials are published only to
the corresponding application item and namespace.

`B2ObjectStorage` is the narrow application-storage contract. A claim selects
an existing bucket-name Secret, an application-key name and a display-named
1Password item. The composition creates or adopts one private bucket with B2
server-side encryption and a one-day hidden-file lifecycle, then creates or
adopts one bucket-scoped read/write application key. The storage API endpoint is
discovered from each account authorisation response rather than fixed to an
account-specific URL. Capabilities are fixed by the composition; claims cannot
request account, bucket-management or key-management access. A same-name key
with different or duplicate settings blocks reconciliation instead of creating
another credential. The generated key is masked into the selected application
Secret and pushed only to that application item. Deleting a claim or composed
request does not delete the external bucket or key.

The non-reconciled fixture in `platform/automation/b2/fixtures` exercises the
claim schema during `mise run check` without creating an external resource.

App-scoped external resources default to orphan-on-delete. ExternalDNS is
upsert-only. Deleting a Kubernetes declaration must not delete an external
bucket, credential, identity client or unrelated WAF rule.

Homepage runs on every cluster and uses the Services and Servers tab
structure, service metadata and custom card styling, including the
repository-owned retained background. Each instance discovers only its local
cluster. The `mbk` instance is served at `home.excloo.com` and
`homepage.mbk.excloo.dev`; the `syd` instance is served at
`homepage.syd.excloo.dev`. Their shared static configuration contains only
non-cluster services and provider bookmarks. Static cards use the same weights
as discovered cards, so cards merge alphabetically; credential-backed widgets
sort first. Each instance extracts its optional widget credentials from the
display-named `Homepage` item in its cluster vault. Missing values hide only the
corresponding widget and do not block the dashboard. The non-root Homepage
container keeps its Next.js prerender cache writable so the initial response
uses current configuration rather than the image's bundled default page.

Beszel agents run as a DaemonSet on every Kubernetes node, including Talos
control-plane nodes. They use outbound WebSocket registration and the Kubernetes
node name as their stable system identity and retain their fingerprint in
per-node host storage. The `mbk` agent reaches its local hub through the cluster
Service; the `syd` agent reaches the `mbk` hub through the private HTTPS route.
This provides node-level CPU, memory, load, uptime and network summaries;
VictoriaMetrics remains authoritative for Kubernetes objects, Pod resources and
detailed node metrics.

Dozzle is not deployed. Kubernetes log aggregation remains in VictoriaLogs and
Grafana, with Headlamp or `kubectl` for live Pod inspection; Beszel remains the
system-level dashboard rather than a second Kubernetes log interface.

## Storage & Recovery

`kimbap` serves retained NFS storage at `10.4.0.3`. The `truenas-nfs` class
creates retained directories beneath `/mnt/truenas-nvme/clusters/mbk`.
Allow-listed standalone datasets use retained static volumes.

`taco` holds the active Kubernetes node-local volumes, including current
CloudNativePG database volumes. Critical database workloads write validated
logical backups to retained NFS. Replaceable caches, metrics and logs may remain
node-local.

| Tier        | Local retention         | Off-site retention                             |
| ----------- | ----------------------- | ---------------------------------------------- |
| Critical    | Daily TrueNAS snapshots | Weekly Hotdog replication and weekly B2 export |
| Important   | Daily TrueNAS snapshots | Weekly Hotdog replication                      |
| Replaceable | None or short retention | None                                           |

Pocket ID has active database-backup and complete application-export schedules.
Its restore CronJob is intentionally suspended and manual: stop the active
authority, provide the exact retained archive path and SHA-256 digest, and
verify the encryption key before creating a restore Job. RoMM has an active
logical-backup schedule.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

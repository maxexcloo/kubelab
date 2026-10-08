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

Install jq and wget (`brew install jq wget` on macOS), then install the remaining pinned tools
and hooks through [Mise](https://mise.jdx.dev/):

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
| `mise run setup`                          | Install tools and Git hooks                                                 |
| `mise run status <cluster> [application]` | Show reconciliation status or watch one app upgrade                         |

### Application Changes

Keep Helm releases and supporting resources in `apps/base/<application>` and
include them through `apps/overlays/<cluster>`. Keep differences in overlays;
do not copy application bases. Larger apps separate secrets and storage into
`external-secrets.yaml` and `storage.yaml`. Keep substantial app settings in their
native configuration file beside the app; keep small environment blocks inline.
Redlib uses `redlib.toml`, with a content-named ConfigMap that triggers a rollout
when its configuration changes. Automation packages separate their API
schema (`definition.yaml`) from implementation (`composition.yaml`).
Select each cluster's external automation in
`clusters/<cluster>/automation` and keep app-specific identity, DNS and WAF
declarations beside their app.
Keep cluster-specific declarations in overlays. Grafana's integrations live beside
its `mbk` monitoring configuration and reconcile after the automation APIs exist.

### Bootstrap

After `homelab` provisions the substrate, run `mise run bootstrap syd` with a
matching kubeconfig context. The task confirms the context and API endpoint,
installs Cilium, validates and injects the provisioned 1Password Connect credentials and token,
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
5. Applications reconcile with their integration claims; Grafana integrations
   reconcile separately after automation.

Monitoring, platform certificates and dashboards report their own health without
blocking unrelated upgrades. Identity, DNS and WAF claims retry until their own
namespace, credentials and API are available. The `apps` stage reports aggregate
workload and app-integration health. Failed stages retry after 30 seconds;
dependency checks retry after five seconds.

Shared policy lives in `platform/bootstrap/flux-reconciliation`. Flux is the
routine deployer; CI only validates. Checks render each Kustomize target once into a temporary directory shared by
manifest-schema and service-metadata validation. They also cover secret
reconciliation and focused external-API fixtures. Render changed
Helm charts separately; schema checks do not validate their generated workloads.

### Resources

Requests guide scheduling; CPU requests also control sharing under contention.
They do not preallocate RAM or cap CPU bursts. Keep CPU limits off trusted
workloads unless isolation needs a specific cap. Helm chart defaults can add
limits even when a value is omitted; check the rendered workload.

Size requests from normal busy-period usage and memory limits above observed
startup and workload peaks. Allow room for Chromium rendering, image processing
and rolling upgrades. Use upstream guidance and conservative workload estimates when history is
limited, then refine them with a representative week of VictoriaMetrics data.
Do not lower limits merely to reduce the sum of configured ceilings.

Tailscale proxy resources use the operator's native `ProxyClass` API. Bound application concurrency when overlapping work,
rather than a single operation, causes the peak.

Distinguish `Insufficient cpu` scheduling failures, CPU throttling, container
memory-limit stalls or `OOMKilled`, and actual node `MemoryPressure`. A container
can stall at its limit while the node has free RAM. Check kubelet memory-limit
events and pressure alongside usage; a healthy Pod or open TCP port alone does
not establish application health. Kubernetes HTTP probes should use supported
application health endpoints where available.

VictoriaMetrics collects kubelet container and node metrics with seven-day
retention. Its operator watches the cluster so node discovery and cross-namespace
scrapes work, and manages collector RBAC. Sydney keeps smaller CPU requests to
leave scheduling room for upgrades. Metrics Server supplies the Kubernetes Metrics
API on both clusters for Homepage, Headlamp and `kubectl top`. Its API serving
certificate is issued and rotated by cert-manager. Kubelet collection uses
`--kubelet-insecure-tls` because Talos currently serves self-signed certificates
without IP SANs; requests remain authenticated over TLS.

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
Bifrost, BookOrbit, CLI Proxy API, Comfy Control, Homepage, Immich,
LaraPaper, Linkwarden, Miniflux, Open WebUI, OpenSpeedTest, Papra, Pocket ID,
RoMM, Shelfmark and Windmill. `syd` runs Anisette, Beszel Agent, OpenSpeedTest
and Redlib.

Companion caches, search services and Redlib's `ctrld` DNS proxy belong to their
apps. Stateful or migration-owning single replicas use recreate updates;
stateless Cloudflared and Redlib use rolling updates.

### Homepage

Homepage runs once on `mbk`, at `home.excloo.com` and
`homepage.mbk.excloo.dev`. Local HTTPRoutes use native discovery. A sidecar reads
other clusters' `gethomepage.dev` annotations from Git every five minutes using
the route extraction shared with Gatus. Apps keep the same metadata and widget
configuration when moved between clusters. Remote cards use URL health checks;
Headlamp provides live Pod inspection. Git describes desired placement, so remote
cards can briefly differ while Flux reconciles. Duplicate remote names gain an
uppercase cluster suffix. Cluster-specific tools use explicit names such as
`Headlamp (MBK)` and `Headlamp (SYD)`. Within each group, cards with widgets come
first, then names sort alphabetically; annotated widget cards use `gethomepage.dev/weight: "-100"`.

Display names use product branding for apps, uppercase cluster qualifiers for
cluster-specific tools, and network-prefixed names for machines. Homepage uses
translucent rounded cards and enlarged text, with native widget spacing and card
heights. Legacy font rendering preserves text weight. Native status labels show
HTTP response times in milliseconds; local Kubernetes cards also label Pod status.
These labels use native tabs at the card's top edge, with widget statistics inside
the same card.
Application routes declare URL checks in their annotations for consistent checks
across clusters. Provider bookmarks, host console links and Home Assistant ingress
shortcuts are navigation, not independent service-health checks. Machine cards use
lowercase names such as `mbk-bento` and `syd-hsp`, with standard platform icons where
available; their Beszel widgets report host statistics. Switching native tabs
mounts the visible widgets and fetches their data; configuration changes trigger Homepage's
normal automatic reload.

External links use `homelab://<network>/<machine>/<service>` references, optionally
followed by a path. Homelab owns hostnames, domains and ports: `management` uses
the HTTPS management port and named services use their declared scheme and port.
Machines with management endpoints receive links unless an existing card already
covers that endpoint. Provider bookmarks come from Homelab's `data/providers.yaml`.
Homelab publishes non-secret Cloudflare account/tunnel IDs and Tailscale device
IDs in each cluster vault's `Infrastructure Inventory` item. A separate
ExternalSecret mounts this snapshot only into the renderer. Homelab refreshes it
on infrastructure apply; the renderer never accesses state or discovers provider
identities itself. Hosts marked `beszel: true` use native Beszel system-name
lookup. Beszel's endpoint comes from its app namespace's route annotations.
Machine widgets join existing appliance cards where possible, covering Talos and
other operating systems without duplicate cards or hardcoded IDs. Cloudflare and
Tailscale identities still supply machine navigation links.
Home Assistant add-ons with only an authenticated ingress link remain navigation
links; ESPHome and
Zigbee2MQTT need dedicated API endpoints before their native widgets can work.

The sidecar reads public Git snapshots without credentials or infrastructure API
access. It retains valid configuration during outages, validates each refresh
and replaces changed files atomically. It uses pinned upstream yq and Flux CLI
images without installing packages at startup. Content-named ConfigMaps trigger updates for checked-in configuration and scripts. Layout
groups are derived automatically; `settings.yaml` supplies presentation choices.

External Secrets supplies mounted files from MBK's 1Password vault. Homepage uses
native `HOMEPAGE_FILE_*` references, so credentials never enter generated config.
Beszel and local Grafana reuse their existing items. Only Homepage can read
the widget credentials; the renderer reads the non-secret inventory and preserves
credential placeholders. Native widgets remain visible when credentials are missing
or their API is unavailable, using Homepage's default error display. An empty
widget container reserves one row while readings load. Homepage 2.4.0's
incompatible annotation-based Beszel overview is omitted; per-machine Beszel
widgets use the supported numeric version setting.

Populate the fields below in the `Homepage` item using credentials from each
service's supported UI. The widgets are already configured:

| Fields                                         | Purpose                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------- |
| `cloudflare-key`                               | API token with Cloudflare Tunnel Read permission                    |
| `grafana-syd-username`, `grafana-syd-password` | Sydney Grafana dashboard login                                      |
| `home-assistant-key`                           | Home Assistant long-lived access token                              |
| `immich-key`                                   | Immich API key                                                      |
| `linkwarden-key`                               | Linkwarden access token                                             |
| `miniflux-key`                                 | Miniflux API key                                                    |
| `syncthing-key`                                | Syncthing API key                                                   |
| `tailscale-key`                                | Tailscale API token with device read access, not a registration key |
| `truenas-key`                                  | TrueNAS API key                                                     |
| `unifi-key`                                    | UniFi API key                                                       |

Widget-first ordering includes configured widgets even when credentials are
empty or their API is unavailable. Links remain usable and widget errors stay
visible. Secret files refresh hourly and Homepage reads updates without a restart. If an app's credential source changes vault, update its ExternalSecret
reference; placement alone does not move dashboard credentials. Existing unused
1Password fields are preserved. `siteMonitor` explicitly enables URL checks;
navigation links alone do not imply service health.

For an offline preview using local checkouts:

```shell
HOMELAB_DIRECTORY=../homelab KUBELAB_DIRECTORY="$PWD" mise exec -- \
  sh apps/base/homepage/render_dashboard.sh apps/base/homepage /tmp/homepage-preview
```

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

Cloudflare-proxied services also have separate routes on the private Gateway,
using the same hostnames and application authentication. Their `PrivateDNSRecord`
selects `spec.crossplane.compositionRef.name: private-dns-record-control-d-only`.
This composition creates only a Control D rule; public ExternalDNS retains the
proxied tunnel record. Separate private routes carry no public-access label, so
public ExternalDNS cannot publish their targets. Both compositions share the same
Control D implementation and default to the existing private-services profile
`653224sydwhf`. Each cluster discovers its own Tailscale IPv4 and IPv6 addresses
from `private.<cluster>.excloo.dev`; `spec.target` only sets the public CNAME in
the default composition. The new Control D-only claims set `spec.ipv6Enabled:
false` because both Traefik Services are IPv4-only. These rules return a Tailscale
A record and `::` for AAAA. Omitting the IPv6 target allows Control D to return
the public AAAA record, which would send IPv6 clients through Cloudflare. The default remains `true` for existing claims;
this rollout does not change their DNS rules. Private IPv6 requires a separate
cluster dual-stack migration before enabling it for these claims.

Clients using that profile reach BookOrbit, Immich, LaraPaper, Linkwarden,
Pocket ID, Redlib, RoMM and Shelfmark over Tailscale, bypassing Cloudflare's WAF.
Control D profile selection is independent of Tailscale connectivity: these names
require Tailscale while the profile is active. Other resolvers retain the public
Cloudflare path. Browsers using their own DNS resolver must use the same profile
to take the private path. Control D rules also cover subdomains, so Sydney serves
Redlib's `www` redirect and its dedicated certificate on the private Gateway.

For rollout, use two Git revisions: first reconcile and verify private routes
and certificates, then add the Control D claims. Sydney also needs a populated
`Control D` password in its cluster vault before the claims can reconcile. Check
each hostname against its cluster's Tailscale IPv4 address with `curl --resolve`,
then verify the private A answer and `::` AAAA answer through the profile and
test normal HTTPS access. Confirm public DNS still points through Cloudflare.
For rollback, disable the new Control D rules before removing private routes;
orphan-on-delete means removing claims alone does not remove the overrides.

`www.reddit.excloo.com` is DNS-only to Sydney's direct Gateway and redirects to
`reddit.excloo.com`. Its separate certificate isolates it from cluster wildcard
renewals. DNS-01 follows `homelab`'s CNAME delegation and uses public resolvers
for self-checks.

`scripts/render_service_inventory.sh` emits normalised route metadata as JSON;
`--include-static` adds Homepage's external monitored services.
After a validated push to `main`, CI dispatches `flylab` with that commit
SHA to refresh Gatus. Store a GitHub token in the repository Actions secret
`HOMELAB_FLY_DEPLOY_TOKEN`, with Actions write access only to
`maxexcloo/flylab`. This is a GitHub workflow-dispatch credential, not a Fly
API token. The default repository token cannot dispatch another repository's
workflow. Install the receiving Fly workflow before enabling this dispatch.
Rendering uses Git configuration and needs no cluster credentials.
Routes can set `monitoring.excloo.dev/alerts: "false"` to suppress external
monitoring alerts while retaining checks. Omitting it enables alerts; other
values are rejected.

## Secrets & External Automation

1Password is the root of trust. Each app uses a display-named item in its cluster
vault (`Cluster: MBK` or `Cluster: SYD`). The vault supplies cluster scope, so item
titles omit the matching Homepage cluster suffix. Only declared internal credentials are generated; non-empty operator
values are preserved except fields explicitly declared as constants. Existing
credentials, tags, URLs and field order are preserved. Category changes replace
the item; duplicate titles stop reconciliation before any writes. Credentials,
kubeconfigs and rendered Secrets stay out of Git.
Application administrators use upstream setup flows; no job provisions accounts
through application APIs.

Crossplane runs on both clusters. `mbk` automates Pocket ID clients and groups,
sending-only Resend keys, and private Cloudflare/Control D DNS. `syd` automates
Redlib's `CloudflareWAFPolicy` and Control D DNS. B2 is available on both and
provisions Beszel's bucket and key on `mbk`. Only selected integrations load
provider credentials.

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
rule. The 1Password reconciler archives unreferenced items tagged only `Kubelab`
after apps reconcile the current Git revision. Restore archived items before
restoring workloads. Archival pauses when the apps Kustomization or its Git source
is suspended. It never modifies `Homelab` items; external resource cleanup
remains manual.

Pocket ID automation updates existing clients. Restore its database and the app
items containing client credentials before dependent workloads. Grafana keeps
separate local-admin and OIDC Secrets, with optional OIDC references at startup
for local recovery access.

## Storage & Recovery

`kimbap` serves NFS at `10.4.0.3`. The `truenas-nfs` class retains directories
under `/mnt/truenas-nvme/clusters/mbk`; allow-listed standalone datasets use
retained static volumes. `taco` holds active node-local volumes, including
CloudNativePG databases. Storage snapshots and off-site replication belong to
`homelab`.

RoMM mounts `truenas/games/roms` and `truenas/games/bios` through subpaths of its
retained `games` volume. Its configuration, resources and user assets remain on
`truenas-nvme/romm` through explicit `config`, `resources` and `assets` subpaths;
no legacy library mount directories are kept on NVMe. Archived source trees live
in `truenas/games/legacy`. PostgreSQL remains node-local. Library sorting is a one-off
maintenance operation, with no ingest or client-export pipeline.

Bifrost 2 performs irreversible migrations. Before upgrading from Bifrost 1,
stop the app and back up its retained volume; follow the upstream
[migration guide](https://docs.getbifrost.ai/migration-guides/v2.0.0).

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

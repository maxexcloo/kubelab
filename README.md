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
include them through `apps/overlays/<cluster>`. Each app’s `settings.yaml` is a native
HelmRelease patch containing its hostname, presentation and editable environment
settings. Homepage uses `release-settings.yaml` because its own application
already calls its layout file `settings.yaml`. Deployment wiring and derived
URLs stay in `helm-release.yaml`. Kustomize replacements carry the canonical
hostname into routes, app URLs, DNS and identity callbacks; `app.invalid` marks
replacement targets, not another setting to edit. Standalone routes keep their
canonical hostname in `route.yaml` or their cluster route file. Keep differences in overlays;
do not copy application bases. Larger apps separate secrets and storage into
`external-secrets.yaml` and `storage.yaml`. Keep substantial app settings in their
native configuration file beside the app; keep small environment blocks inline.
Redlib uses `apps/base/redlib/settings.yaml`, a native HelmRelease values patch.
Edit its YAML subscription list and environment settings there; the chart joins
subscriptions into Redlib’s native environment variable and Flux rolls out the
change. No generated application config or startup adapter is required. Automation packages separate their API
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

`mbk` runs Actual Budget, Actual Up, AIOMetadata, AIOStreams, Beszel, Beszel Agent, Bichon,
Bifrost, BookOrbit, CLI Proxy API, Comfy Control, Homepage, Immich,
LaraPaper, Linkwarden, Miniflux, Open WebUI, OpenSpeedTest, Papra, Pocket ID,
RoMM, Shelfmark and SideStore VPN. `syd` runs Anisette, Beszel Agent, OpenSpeedTest
and Redlib.

Companion caches, search services and Redlib's `ctrld` DNS proxy belong to their
apps. Stateful or migration-owning single replicas use recreate updates;
stateless Cloudflared and Redlib use rolling updates.

AIOMetadata caches requests on demand. Essential and popular background warming
are disabled because provider keys belong to saved user configurations rather
than the instance. MAL background warming is also disabled while the Jikan API
is unreachable; user-requested MAL lookups still depend on that API. Redis uses a
192 MiB cache ceiling within its 256 MiB container limit and evicts expiring cache
entries with `volatile-lfu`, preserving non-expiring operational keys.
AIOStreams fetches its commit-pinned templates at startup or on manual refresh;
only their regex and SEL sources refresh hourly. Its startup probe allows two
minutes before liveness checks begin.

### Bifrost

Providers and MCP connections are managed through Bifrost's native interface and
persist in its configuration database. The official Bifrost image uses native Helm
init containers with the official Astral image to supply pinned `uv`, `uvx` and
Python in a shared pod-local volume. Python package caches persist on the existing
data volume. No custom image or startup wrapper is required.

Python STDIO connections use `/opt/mcp/uvx` with a pinned package version. Include
`PATH`, `UV_CACHE_DIR`, `UV_LINK_MODE`, `UV_PYTHON`, `UV_PYTHON_DOWNLOADS` and
`UV_PYTHON_INSTALL_DIR` in the connection's environment allowlist, alongside its
credential variables. HTTP MCP connections need no local runtime.
UniFi Network uses the `api-key-unifi` field in the cluster's `Bifrost` 1Password
item for inventory and supported Integration API tools. The reconciler creates
this field empty when missing and preserves supplied keys; UniFi issues the key.
Legacy tools requiring a local admin session remain unavailable with API-key-only
authentication.
Pi, Antigravity, Codex and OpenCode connect to `https://bifrost.excloo.com/mcp`
using Bifrost's MCP-only `Agents` virtual key, stored as `api-key-mcp` in the same
1Password item. Manage upstream servers centrally in Bifrost; client files keep
only their native HTTP connection settings.

### Homepage

Homepage runs once on `mbk`, at `home.excloo.com` and
`homepage.mbk.excloo.dev`. Its sidecar reads all clusters' `gethomepage.dev`
annotations from Git every five minutes using the route extraction shared with
Gatus. The same annotations supply category cards and host copies. Kubernetes
route discovery is disabled to prevent duplicates; local cards retain native
`app`, `namespace` and Pod selectors for live Kubernetes statistics. Remote cards
use URL health checks; Headlamp provides live Pod inspection. Git describes
desired placement, so cards can briefly differ while Flux reconciles.

Services appear in their category on Services and under `Cluster: MBK` or
`Cluster: SYD` on Servers. Machine services remain under their inventory host.
Cluster groups describe ownership, not Pod placement, and support any node count.
Cluster tools with `gethomepage.dev/group: Servers` appear only in their cluster
group. Cluster tunnel widgets belong to the cluster; host monitoring belongs to
the machine. Only typed inventory machines receive host cards.
Category subtitles include location; server copies omit it. Widget cards come
first, followed by alphabetical names.

Homepage uses translucent rounded cards and enlarged system UI text, with native
widget spacing and card heights. HTTP response times appear in milliseconds;
local Kubernetes cards also show Pod status. Switching native tabs mounts the
visible widgets and fetches their data. Configuration changes trigger Homepage's
normal automatic reload.

Public links can use `homelab-dns://<CNAME-target>` to resolve a single hostname
from Homelab’s DNS declarations. Gatus uses its Fly app’s CNAME target; Homepage
does not need access to the private Flylab repository.
External links use `homelab://<network>/<machine>/<service>`, optionally followed
by a path. Homelab owns hostnames, domains and each service's `name`, `scheme` and
`port`; management consoles use `services.management`. HTTP links use the preferred
host in Homelab's infrastructure snapshot; HTTPS links retain the certificate
hostname. Missing snapshots retain the canonical hostname.
Services with `description`, `icon` or `group` metadata produce Homepage cards
(default group: Servers). Existing appliance cards prevent duplicate management links.
Provider bookmarks and Cloudflare/Tailscale widget settings come from Homelab's
`data/providers.yaml`; provider identities come from the infrastructure snapshot.

Homelab publishes non-secret Cloudflare account/tunnel IDs and Tailscale device
IDs in each cluster vault's `Infrastructure Inventory` item. A separate
ExternalSecret mounts this snapshot only into the renderer. Homelab refreshes it
on infrastructure apply; the renderer never accesses state or discovers provider
identities itself. Hosts marked `beszel: true` use native Beszel system-name
lookup. Beszel's endpoint comes from its app namespace's route annotations.
Beszel, Cloudflare Tunnel and Tailscale have separate cards under each host.
Native widget fields match the legacy dashboard, including TrueNAS pool rows.

Application routes declare URL checks in their annotations. Provider bookmarks,
host console links and Home Assistant ingress shortcuts are navigation links.
Home Assistant add-ons with only an authenticated ingress link cannot supply
native widgets. ESPHome needs a direct dashboard API endpoint; Homepage has no
native Zigbee2MQTT widget.

The sidecar reads public Git snapshots without credentials or infrastructure API
access. It retains valid configuration during outages, validates each refresh
and replaces changed files atomically. It uses pinned upstream yq and Flux CLI
images without installing packages at startup. Content-named ConfigMaps trigger
updates for checked-in configuration and scripts. Layout groups are derived
automatically; `settings.yaml` supplies presentation choices. Providers is always
the final group on the Services tab.

External Secrets supplies mounted files from MBK's 1Password vault. Homepage uses
native `HOMEPAGE_FILE_*` references, so credentials never enter generated config.
Beszel reuses its existing item. Both Grafana widget logins live in the `Homepage`
item with explicit cluster prefixes. Only Homepage can read
the widget credentials; the renderer reads the non-secret inventory and preserves
credential placeholders. Native widgets remain visible when credentials are missing
or their API is unavailable, using Homepage's default error display. An empty
widget container reserves one row while readings load. Beszel shows an overview
on Services and host readings on Servers. Widget version annotations are parsed
as YAML so native widgets receive numeric API versions where required.

Populate the fields below in the `Homepage` item using credentials from each
service's supported UI. The widgets are already configured:

| Fields                                         | Purpose                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------- |
| `cloudflare-api-token`                         | API token with Cloudflare Tunnel Read permission                    |
| `grafana-mbk-password`, `grafana-mbk-username` | MBK Grafana dashboard login                                         |
| `grafana-syd-password`, `grafana-syd-username` | SYD Grafana dashboard login                                         |
| `home-assistant-access-token`                  | Home Assistant long-lived access token                              |
| `immich-api-key`                               | Immich API key                                                      |
| `linkwarden-access-token`                      | Linkwarden access token                                             |
| `miniflux-api-key`                             | Miniflux API key                                                    |
| `syncthing-api-key`                            | Syncthing API key                                                   |
| `tailscale-api-token`                          | Tailscale API token with device read access, not a registration key |
| `truenas-api-key`                              | TrueNAS API key                                                     |
| `unifi-api-key`                                | UniFi API key                                                       |

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
`syd` uses its private HTTPS route. Agent network totals include only the node's
primary interface (`ens2` on `mbk`, `eth0` on `syd`), excluding Cilium and Tailscale
interfaces to avoid counting the same traffic again. Use VictoriaMetrics for Pod metrics,
VictoriaLogs/Grafana for logs, and Headlamp or `kubectl` for live inspection.
Workload/Flux notification delivery is not configured.

Beszel's login-location emails are disabled for users and superusers in its saved
authentication settings. SMTP uses the app's managed Resend key; update the saved
SMTP password after rotating it. These settings are maintained through Beszel's
administration interface, not a reconciliation job.

## Networking & Ingress

Apps own their routes and DNS. `homelab` owns cluster wildcards, stable targets,
tunnel credentials and DNS for services outside Kubernetes.

| Mode          | Gateway         | DNS target                    | Cloudflare proxy |
| ------------- | --------------- | ----------------------------- | ---------------- |
| Direct public | `public-direct` | `public.<cluster>.excloo.dev` | Per route        |
| Internal      | `private`       | Cluster Tailscale wildcard    | None             |
| Tunnel public | `public-tunnel` | `tunnel.<cluster>.excloo.dev` | Required         |

Cluster values live in `clusters/<cluster>/settings/settings.yaml`; shared site
settings live in `platform/settings/settings.yaml`. Native Kustomize components
apply them to each reconciliation boundary. These ConfigMaps are marked local
configuration and are not deployed. The NFS endpoint is an explicit storage-network
contract; it must match Homelab’s storage interface, not its management address.
Pocket ID’s hostname is the site-wide `identity_host` setting because both
apps and platform consumers use it. Its app settings contain its other preferences. Control D profile selection, private gateway targets and Grafana hostnames no
longer live as environment-specific defaults inside controller implementations.

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
Gatus reads machine-service checks directly from Homelab; dashboard configuration
is not a monitoring input.
After a validated push to `main`, CI dispatches `flylab` with that commit
SHA to refresh Gatus. Store a GitHub token in the repository Actions secret
`HOMELAB_FLY_DEPLOY_TOKEN`, with Actions write access only to
`maxexcloo/flylab`. This is a GitHub workflow-dispatch credential, not a Fly
API token. The default repository token cannot dispatch another repository's
workflow. Install the receiving Fly workflow before enabling this dispatch.
Rendering uses Git configuration and needs no cluster credentials.
Routes opt into checks with `monitoring.excloo.dev/enabled: "true"`, independently
of dashboard visibility. The primary hostname supplies the HTTPS probe URL;
`monitoring.excloo.dev/path` changes its path. Explicit header Secret references
use `monitoring.excloo.dev/headers`, a JSON map from header name to namespace-local
Secret `name` and `key`. Gatus resolves the referenced ExternalSecret through
1Password in GitHub Actions; it no longer parses WAF expressions.
Routes can set `monitoring.excloo.dev/alerts: "false"` to suppress external
monitoring alerts while retaining checks. Omitting it enables alerts; other
values are rejected.

### Actual Up

`actual-up` runs on `mbk` as a single-replica app with a private route at
`https://actual-up.mbk.excloo.dev`. The separate `actual-up` repository builds and
publishes its image; this repository owns its configuration and deployment.
The public `ghcr.io/maxexcloo/actual-up` image is pinned by version and digest.
Upstream setup happens in the browser after deployment.
The image supports anonymous pulls, so no registry credential is required.

The `Actual Up` item in `Cluster: MBK` supplies generated `encryption-key` and
`password` fields and default `username`. External Secrets injects these as
`ACTUAL_UP_ENCRYPTION_KEY`, `ACTUAL_UP_PASSWORD` and `ACTUAL_UP_USERNAME`.
The app uses a normal sign-in page. Roll the app after rotating its login.
Preserve the encryption key with the encrypted settings backup; replacing it
without re-encryption makes saved credentials unreadable.

`apps/base/actual-up/config.yaml` starts with no keys or mappings and automatic
sync enabled. On the **Connections** page, enter the Actual server, budget sync
ID and session token (or password), add Up API keys, then connect accounts.
API keys and Actual credentials are checked and encrypted in the app; no
per-account ExternalSecret edits or restarts are needed. The app has no access
to 1Password itself. Existing upstream fields in 1Password are preserved but
are no longer consumed by this deployment.

Saving a mapping backfills its history. Full backfills also run on startup and
nightly at 03:00, with recent transactions synced every 15 minutes. Set
`schedule.enabled: false` to preview first. Map a shared bank account once,
selecting both partners’ keys in fallback order. Only Actual Up pods are
additionally permitted through Actual Budget’s ingress policy. No public webhook
route is needed for polling.

Browser settings persist as authenticated AES-256-GCM ciphertext in
`/data/settings.json` on the app’s 1Gi NFS claim. Back up this file and its
1Password encryption key together. Actual’s rebuildable budget cache uses local pod storage at `/tmp/actual-cache`,
not NFS, and is not encrypted by the settings encryption. The last 20 run results and
queue are in memory and reset on restart. Automatic full-history backfills
recover older gaps after outages or interrupted imports without a cursor database.

### SideStore VPN

SideStore VPN runs on `mbk` with its own Tailscale identity,
`sidestore-vpn`. It advertises only `10.7.0.1/32`, with subnet NAT disabled
so the reflector can return packets to the requesting iOS device. Approve this
route on that device in the Tailscale admin console; no LAN route or exit node
is needed. Homelab's tailnet policy must also allow traffic from `10.7.0.1/32`
to the iOS devices' owners (`group:admin`). Reflection preserves ports, so this
return traffic is a new connection rather than an ordinary connection reply.
Without that grant, route approval alone does not make SideStore work.
The `SideStore VPN` item in `Cluster: MBK` supplies its `auth-key`.
Tailscale state persists on a local-path volume. Replace an expired registration
key before rebuilding a lost identity; existing authenticated state survives key
expiry. The upstream reflector has no versioned releases, so its image is pinned
by digest; the separate Tailscale container uses a stable release.

On iOS, connect to Wi-Fi, enable Tailscale and turn off LocalDevVPN. In current
SideStore builds, open **Settings → Connection Config**, keep **Use Local VPN**
enabled and set **User Configuration → Device IP** to `10.7.0.1`. This selects
the reflector instead of the automatically discovered tunnel peer. Leave
**RemotePair Port** at its default. Check device reachability and refresh an app
in SideStore to verify the complete path. Older fixed-address SideStore builds
do not need the Device IP override. Pairing and Anisette setup remain SideStore
prerequisites.

## Secrets & External Automation

1Password is the root of trust. Each app uses a display-named item in its cluster
vault (`Cluster: MBK` or `Cluster: SYD`). The vault supplies cluster scope, so item
titles omit the matching Homepage cluster suffix. Only declared internal credentials are generated; non-empty operator
values are preserved except fields explicitly declared as constants. Existing
credentials, tags, URLs and field sections are preserved. Custom fields sort
alphabetically within each section; 1Password retains its built-in login fields.
New application login defaults use `max@excloo.com`; existing service accounts
must be renamed through their supported interfaces before updating stored logins. Category changes replace
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
manually in Beszel's Backups screen; no repository job configures the app or runs
its backups. Beszel's built-in weekly schedule retains three backups in
`excloo-mbk-beszel`. After changing the bucket or rotating its key, update the
saved backup settings from the item and verify a new backup; publishing new
credentials does not update Beszel's saved configuration.

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

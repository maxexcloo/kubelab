# Migration Inventory

This is the cutover checklist for the current estate. It is documentation, not
an application API or generator input. Update a row when its ownership or
strategy changes; keep the actual desired state in normal Kubernetes, Flux,
Helm, and OpenTofu configuration.

No row marked `migrate`, `replace`, or `retire` is complete until its route,
identity, secrets, storage, backups, monitoring, dashboard entry, rollback, and
old owner have been checked.

## Cutover controls

- `Public` uses an explicitly approved Cloudflare Tunnel route. `Internal` uses
  Tailscale and split DNS. `Private` has no application route. `None` has no
  network endpoint.
- Critical state uses retained NFS or CloudNativePG, daily snapshots, off-site
  backup, and an application-native export where available. Important state
  uses retained NFS and the Important backup tier. Unclassified state is
  replaceable from Git, 1Password, or upstream data.
- Every routed user interface gets a Homepage entry and a direct Gatus probe.
  Agents and backends are checked through their owning service. Retired
  services lose checks only after their final consumer is gone.
- A migration or replacement keeps the old deployment stopped but recoverable
  for the rollback window. Rollback restores its route and, for stateful
  services, the final snapshot or export. Retirement restores the archived old
  owner only if a missed consumer is found. Retained systems do not transfer
  ownership.

## Kubernetes and application services

| Service                       | Current owner                          | Destination                  | Strategy      | Access   | Data and integrations                                                                                              |
| ----------------------------- | -------------------------------------- | ---------------------------- | ------------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| Actual Budget                 | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical NFS data, Pocket ID                                                                                       |
| AIO Metadata                  | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                                                                        |
| AIOStreams                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important NFS configuration                                                                                        |
| Anisette                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Stateless                                                                                                          |
| Beszel                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical data, B2, Pocket ID, Resend                                                                               |
| Beszel agents                 | `homelab` target repositories          | Cluster and appliance owners | Replace       | Private  | Flux owns cluster agents; retained appliances need a documented native service, upgrade path, and credential owner |
| Bichon                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical mail archive                                                                                              |
| Bifrost                       | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Important configuration, CLIPROXYAPI and Comfy Control                                                             |
| BookOrbit                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical library, Pocket ID, Resend                                                                                |
| Byparr                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Stateless backend for Shelfmark                                                                                    |
| CLIPROXYAPI                   | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Replaceable credentials and configuration, Bifrost                                                                 |
| Cloudflared                   | `homelab-truenas`                      | Both clusters                | Replace       | Private  | Cluster-specific public ingress connector                                                                          |
| Comfy Control                 | `homelab-truenas`                      | `mbk` plus Mandu             | Replace       | Internal | Controller in Kubernetes; optional GPU worker on Mandu                                                             |
| Dozzle                        | `homelab-truenas`                      | None                         | Retire        | Internal | Replaced by VictoriaLogs, Grafana, and Headlamp                                                                    |
| Dozzle agents                 | `homelab-docker`                       | None                         | Retire        | Private  | Remove after the last Docker workload leaves                                                                       |
| Gatus                         | `homelab-fly`                          | Fly                          | Retain        | Internal | External failure domain, Tailscale, Resend, direct Git config                                                      |
| GitHub runner                 | `homelab-truenas`                      | None                         | Retire        | None     | CI validates only; Flux deploys                                                                                    |
| Grafana                       | `homelab-truenas`                      | `mbk`                        | Replace       | Internal | Platform observability, Pocket ID                                                                                  |
| Homepage                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Native Kubernetes discovery plus direct appliance entries                                                          |
| Immich                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical photos and database, Pocket ID, Resend                                                                    |
| Larapaper                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Important NFS data                                                                                                 |
| Linkwarden                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and archive, Pocket ID, Resend                                                                   |
| Miniflux                      | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical database, Pocket ID                                                                                       |
| OAuth2 Proxy                  | `homelab-docker` and `homelab-truenas` | Both clusters if required    | Review        | Internal | Retain only for apps without direct OIDC or Access support                                                         |
| Open WebUI                    | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical application data, Pocket ID                                                                               |
| OpenSpeedTest                 | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace first | Internal | Disposable learning workload                                                                                       |
| Papra                         | `homelab-truenas`                      | `mbk`                        | Migrate       | Internal | Critical documents, Pocket ID                                                                                      |
| Pocket ID                     | `homelab-truenas`                      | `mbk`                        | Migrate last  | Public   | Critical identity data, Resend, break-glass required                                                               |
| Redlib                        | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Stateless, Cloudflare policy                                                                                       |
| RoMM                          | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Critical database and retained NFS library, Pocket ID                                                              |
| RoMM workflows                | `homelab-workflows`                    | `mbk` Jobs                   | Replace       | None     | Guarded storage-local Jobs; no Actions runner                                                                      |
| Shelfmark                     | `homelab-truenas`                      | `mbk`                        | Migrate       | Public   | Important data, BookOrbit and Byparr dependencies, Pocket ID                                                       |
| Tailscale Kubernetes operator | `homelab` and target repositories      | Both clusters                | Replace       | Private  | Flux-owned operator; OAuth client, tags, and policy stay in OpenTofu                                               |
| Traefik                       | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace       | Private  | Gateway API implementation for internal and public routes                                                          |
| VictoriaMetrics               | `homelab-truenas`                      | Both clusters                | Replace       | Internal | Replaceable platform metrics; home is primary                                                                      |

## Retained appliances and substrate

| System                      | Current owner     | Destination         | Strategy | Notes                                                                                            |
| --------------------------- | ----------------- | ------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| Appliance Tailscale clients | Appliance owners  | Retained appliances | Retain   | Preserve independently of Kubernetes operator and legacy service retirement                      |
| HAOS                        | `homelab`         | HAOS appliance      | Retain   | Includes ESPHome, ESPresense, Matter Hub, Studio Code Server, and Zigbee2MQTT                    |
| Hotdog                      | `homelab`         | Hotdog              | Retain   | Linux/ZFS receiver on 2 GB RAM; do not install Talos                                             |
| Mandu                       | `homelab`         | Bazzite             | Retain   | Rootless Podman Quadlets; optional AMD GPU worker over Tailscale                                 |
| Netboot                     | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local unless migration solves a concrete problem                                    |
| Syncthing                   | `homelab-truenas` | TrueNAS appliance   | Retain   | Keep storage-local; expose status to Homepage/Gatus directly                                     |
| Talos Tailscale extension   | `homelab`         | Both Talos nodes    | Replace  | Host-level recovery path baked into each cluster image; identity stays in cluster OpenTofu state |
| TrueNAS                     | `homelab`         | TrueNAS             | Retain   | Storage, snapshots, replication, and the Taco Talos VM                                           |
| UniFi                       | `homelab`         | UniFi appliance     | Retain   | DHCP reservation, routing, and network policy remain substrate                                   |

## External ownership

| Resource family                                                 | Owner after migration                     | Deletion default               |
| --------------------------------------------------------------- | ----------------------------------------- | ------------------------------ |
| B2 app buckets and keys                                         | Direct Crossplane provider-http resources | Orphan                         |
| Cloudflare app DNS, tunnel routes, Access, WAF, and rate limits | Direct Crossplane provider-http resources | Orphan                         |
| Cluster Cloudflare tunnels and credentials                      | OpenTofu                                  | Prevent accidental replacement |
| Control D app rules                                             | Direct Crossplane provider-http resources | Orphan                         |
| Fly Gatus app, Machine, and secrets                             | OpenTofu exception                        | Reviewed replacement only      |
| Global Tailscale ACLs/grants and tag owners                     | Foundations OpenTofu                      | Reviewed saved plan only       |
| OCI network, image, NSG, and `hsp` VM                           | OpenTofu                                  | Reviewed saved plan only       |
| Pocket ID app clients and groups                                | Direct Crossplane provider-http resources | Orphan                         |
| Resend app keys                                                 | Direct Crossplane provider-http resources | Orphan                         |
| Retained appliance Tailscale identities                         | Appliance owner                           | Explicit appliance procedure   |
| Tailscale operator OAuth clients                                | Cluster-specific OpenTofu                 | Reviewed saved plan only       |
| Talos-node Tailscale bootstrap identities                       | Cluster-specific OpenTofu                 | Reviewed saved plan only       |

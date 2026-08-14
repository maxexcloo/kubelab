# Migration Inventory

This is the cutover checklist for the current estate. It is documentation, not
an application API or generator input. Update a row when its ownership or
strategy changes; keep the actual desired state in normal Kubernetes, Flux,
Helm, and OpenTofu configuration.

No row marked `migrate`, `replace`, or `retire` is complete until its route,
identity, secrets, storage, backups, monitoring, dashboard entry, rollback, and
old owner have been checked.

## Kubernetes and application services

| Service                      | Current owner                          | Destination                  | Strategy      | Data and integrations                                              |
| ---------------------------- | -------------------------------------- | ---------------------------- | ------------- | ------------------------------------------------------------------ |
| Actual Budget                | `homelab-truenas`                      | `au`                         | Migrate       | Critical NFS data, Pocket ID                                       |
| AIO Metadata                 | `homelab-truenas`                      | `au`                         | Migrate       | Important NFS configuration                                        |
| AIOStreams                   | `homelab-truenas`                      | `au`                         | Migrate       | Important NFS configuration                                        |
| Anisette                     | `homelab-truenas`                      | `au`                         | Migrate       | Stateless, public route                                            |
| Beszel                       | `homelab-truenas`                      | `au`                         | Migrate       | Critical data, B2, Pocket ID, Resend                               |
| Beszel agents                | `homelab` target repositories          | Both clusters and appliances | Replace       | Native host agents; no Kubernetes control-plane dependency         |
| Bichon                       | `homelab-truenas`                      | `au`                         | Migrate       | Critical mail archive                                              |
| Bifrost                      | `homelab-truenas`                      | `au`                         | Migrate       | Important configuration, CLIPROXYAPI and Comfy Control             |
| BookOrbit                    | `homelab-truenas`                      | `au`                         | Migrate       | Critical library, Pocket ID, Resend                                |
| Byparr                       | `homelab-truenas`                      | `au`                         | Migrate       | Stateless internal dependency                                      |
| CLIPROXYAPI                  | `homelab-truenas`                      | `au`                         | Migrate       | Replaceable credentials/configuration                              |
| Cloudflared                  | `homelab-truenas`                      | Both clusters                | Replace       | Cluster-specific platform deployment                               |
| Comfy Control                | `homelab-truenas`                      | `au` plus Bazzite            | Replace       | Controller in Kubernetes; optional GPU worker on Bazzite           |
| Dozzle                       | `homelab-truenas`                      | None                         | Retire        | Replaced by VictoriaLogs, Grafana, and Headlamp                    |
| Dozzle agents                | `homelab-docker`                       | None                         | Retire        | Remove after the last Docker workload leaves                       |
| Gatus                        | `homelab-fly`                          | Fly                          | Retain        | External failure domain, Tailscale, Resend, direct Git config      |
| GitHub runner                | `homelab-truenas`                      | None                         | Retire        | CI validates only; Flux deploys                                    |
| Grafana                      | `homelab-truenas`                      | `au`                         | Replace       | Platform observability, Pocket ID                                  |
| Homepage                     | `homelab-truenas`                      | `au`                         | Migrate       | Native Kubernetes discovery plus direct appliance entries          |
| Immich                       | `homelab-truenas`                      | `au`                         | Migrate       | Critical photos/database, Pocket ID, Resend                        |
| Larapaper                    | `homelab-truenas`                      | `au`                         | Migrate       | Important NFS data                                                 |
| Linkwarden                   | `homelab-truenas`                      | `au`                         | Migrate       | Critical database/archive, Pocket ID, Resend                       |
| Miniflux                     | `homelab-truenas`                      | `au`                         | Migrate       | Critical database, Pocket ID                                       |
| OAuth2 Proxy                 | `homelab-docker` and `homelab-truenas` | Both clusters if required    | Review        | Retain only for apps without direct OIDC/Access support            |
| Open WebUI                   | `homelab-truenas`                      | `au`                         | Migrate       | Critical app data, Pocket ID                                       |
| OpenSpeedTest                | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace first | Disposable learning workload                                       |
| Papra                        | `homelab-truenas`                      | `au`                         | Migrate       | Critical documents, Pocket ID                                      |
| Pocket ID                    | `homelab-truenas`                      | `au`                         | Migrate last  | Critical identity data, Resend, break-glass required               |
| Redlib                       | `homelab-truenas`                      | `au`                         | Migrate       | Stateless public route with Cloudflare policy                      |
| RoMM                         | `homelab-truenas`                      | `au`                         | Migrate       | Critical database and retained NFS library, Pocket ID              |
| RoMM workflows               | `homelab-workflows`                    | `au` Jobs                    | Replace       | Guarded storage-local Jobs; no Actions runner                      |
| Shelfmark                    | `homelab-truenas`                      | `au`                         | Migrate       | Important data, BookOrbit and Byparr dependencies, Pocket ID       |
| Tailscale operator/extension | `homelab` and target repositories      | Both clusters                | Replace       | OpenTofu access foundations; standard operator and Talos extension |
| Traefik                      | `homelab-docker` and `homelab-truenas` | Both clusters                | Replace       | One Gateway API implementation per cluster                         |
| VictoriaMetrics              | `homelab-truenas`                      | Both clusters                | Replace       | Platform metrics; home is primary                                  |

## Retained appliances and substrate

| System    | Current owner     | Destination       | Strategy | Notes                                                                         |
| --------- | ----------------- | ----------------- | -------- | ----------------------------------------------------------------------------- |
| Bazzite   | `homelab`         | Bazzite           | Retain   | Rootless Podman Quadlets; optional AMD GPU worker over Tailscale              |
| HAOS      | `homelab`         | HAOS appliance    | Retain   | Includes ESPHome, ESPresense, Matter Hub, Studio Code Server, and Zigbee2MQTT |
| Hotdog    | `homelab`         | Hotdog            | Retain   | Linux/ZFS receiver on 2 GB RAM; do not install Talos                          |
| Netboot   | `homelab-truenas` | TrueNAS appliance | Retain   | Keep storage-local unless migration solves a concrete problem                 |
| Syncthing | `homelab-truenas` | TrueNAS appliance | Retain   | Keep storage-local; expose status to Homepage/Gatus directly                  |
| TrueNAS   | `homelab`         | TrueNAS           | Retain   | Storage, snapshots, replication, and the `au` Talos VM                        |
| UniFi     | `homelab`         | UniFi appliance   | Retain   | DHCP reservation, routing, and network policy remain substrate                |

## External ownership

| Resource family                                                 | Owner after migration                     | Deletion default               |
| --------------------------------------------------------------- | ----------------------------------------- | ------------------------------ |
| B2 app buckets and keys                                         | Direct Crossplane provider-http resources | Orphan                         |
| Cloudflare app DNS, tunnel routes, Access, WAF, and rate limits | Direct Crossplane provider-http resources | Orphan                         |
| Cluster Cloudflare tunnels and credentials                      | OpenTofu                                  | Prevent accidental replacement |
| Control D app rules                                             | Direct Crossplane provider-http resources | Orphan                         |
| Fly Gatus app, Machine, and secrets                             | OpenTofu exception                        | Reviewed replacement only      |
| OCI network, image, NSG, and `au-oci` VM                        | OpenTofu                                  | Reviewed saved plan only       |
| Pocket ID app clients and groups                                | Direct Crossplane provider-http resources | Orphan                         |
| Resend app keys                                                 | Direct Crossplane provider-http resources | Orphan                         |
| Tailscale grants, tags, OAuth, and bootstrap keys               | OpenTofu                                  | Reviewed saved plan only       |

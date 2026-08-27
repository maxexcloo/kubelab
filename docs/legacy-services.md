# Legacy Service Disposition

This inventory audits the `legacy` tag in `homelab`. The annotated tag points to
commit `2a554f9d9be3d0aec7bf04d1c238861e0a54c9b4`, dated 4 August 2026. It is the
last catalogue-style service definition and is read-only migration evidence.

## Service Inventory

| Legacy identifier | Disposition     | Current implementation or owner                                                                       |
| ----------------- | --------------- | ----------------------------------------------------------------------------------------------------- |
| `actual-budget`   | Migrate         | `apps/base/actual-budget`                                                                             |
| `aiometadata`     | Migrate         | `apps/base/aiometadata`                                                                               |
| `aiostreams`      | Migrate         | `apps/base/aiostreams`                                                                                |
| `anisette`        | Migrate         | `apps/base/anisette`                                                                                  |
| `beszel`          | Migrate         | `apps/base/beszel`; B2 inventory under `apps/integrations/b2`                                         |
| `beszel-agent`    | Replace         | `apps/base/beszel-agent` for clusters; appliance owners retain native agents                          |
| `bichon`          | Migrate         | `apps/base/bichon`                                                                                    |
| `bookorbit`       | Migrate         | `apps/base/bookorbit`                                                                                 |
| `byparr`          | Migrate         | `apps/base/byparr`                                                                                    |
| `cloudflared`     | Replace         | `platform/networking/cloudflared`                                                                     |
| `dozzle`          | Retire          | VictoriaLogs, Grafana, and Headlamp replace its log interface                                         |
| `dozzle-agent`    | Retire          | No agent is needed after the previous Docker workloads leave                                          |
| `gatus`           | Retain          | `homelab-fly` remains its bounded owner and independent failure domain; Homepage links to it directly |
| `github-runner`   | Retire          | Flux deploys; storage-local Kubernetes Jobs replace RoMM workflows                                    |
| `homepage`        | Migrate         | `apps/base/homepage` with native cluster discovery and retained static targets                        |
| `immich`          | Migrate         | `apps/base/immich`                                                                                    |
| `larapaper`       | Migrate         | `apps/base/larapaper`                                                                                 |
| `linkwarden`      | Migrate         | `apps/base/linkwarden`                                                                                |
| `miniflux`        | Migrate         | `apps/base/miniflux`                                                                                  |
| `netbootxyz`      | Retain          | TrueNAS application linked directly from Homepage                                                     |
| `oauth2-proxy`    | Retire          | Dozzle retired and Traefik is private; every remaining identity consumer uses native OIDC             |
| `open-webui`      | Migrate         | `apps/base/open-webui`                                                                                |
| `openspeedtest`   | Replace         | `apps/base/openspeedtest` on both clusters                                                            |
| `papra`           | Migrate         | `apps/base/papra`                                                                                     |
| `pocket-id`       | Migrate last    | `apps/base/pocket-id` and `apps/integrations/pocket-id`                                               |
| `redlib`          | Migrate         | `apps/base/redlib`; WAF policy under `apps/integrations/cloudflare`                                   |
| `romm`            | Migrate         | `apps/base/romm`                                                                                      |
| `romm-workflows`  | Replace         | Guarded storage-local Jobs in `apps/base/romm`                                                        |
| `shelfarr`        | Replace         | `apps/base/shelfmark` is the supported successor                                                      |
| `syncthing`       | Retain          | TrueNAS application linked directly from Homepage                                                     |
| `tailscale`       | Split ownership | Flux owns the Kubernetes operator; OpenTofu and appliance owners retain identities and policy         |
| `traefik`         | Replace         | `platform/networking/traefik` with Gateway API                                                        |

## Route Inventory

This includes the two server-scoped routes from the same legacy catalogue as
well as workload routes.

| Legacy hostname             | Disposition                                                                                  |
| --------------------------- | -------------------------------------------------------------------------------------------- |
| `anisette.excloo.com`       | Preserved on the `syd` direct-public Gateway                                                 |
| `books.excloo.com`          | Preserved on the `mbk` public-tunnel Gateway                                                 |
| `budget.excloo.com`         | Preserved on the `mbk` private Gateway                                                       |
| `chat.excloo.com`           | Implemented on the `mbk` private Gateway pending workload reconciliation                     |
| `doco-cd.hsp.au.excloo.net` | Retired with Doco-CD and the previous Docker delivery path                                   |
| `docs.excloo.com`           | Replaced by the reconciled `papra.excloo.com` private route                                  |
| `games.excloo.com`          | Staged privately with RoMM; reviewed public restoration remains a cutover gate               |
| `home-assistant.excloo.com` | Staged as a suspended public webhook-only route                                              |
| `home.excloo.com`           | Replaced by the reconciled `homepage.mbk.excloo.dev` private route                           |
| `id.excloo.com`             | Staged privately with Pocket ID; reviewed public restoration remains the final identity gate |
| `larapaper.excloo.com`      | Preserved on the `mbk` public-tunnel Gateway                                                 |
| `photos.excloo.com`         | Preserved on the `mbk` public-tunnel Gateway                                                 |
| `reader.excloo.com`         | Preserved on the `mbk` private Gateway                                                       |
| `reddit.excloo.com`         | Preserved on the `syd` public-tunnel Gateway                                                 |
| `shelf.excloo.com`          | Preserved by Shelfmark on the `mbk` public-tunnel Gateway                                    |
| `status.excloo.com`         | Retained by `homelab-fly` outside the home failure domain                                    |

## Behavioural Parity

| Legacy behaviour              | Current disposition                                                                                                                                                         |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Beszel B2 bucket              | A suspended provider-http inventory adopts the named legacy bucket and enforces private access, SSE-B2 AES-256, and one-day hidden-file deletion without delete authority.  |
| Beszel B2 key                 | The legacy one-time key secret is preserved in 1Password. Provider-http verifies its identifier, name, bucket scope, and exact capabilities but cannot rotate or delete it. |
| Cloudflare Access             | Retired because no legacy route declared an Access application and every current identity consumer has native OIDC.                                                         |
| Control D hostname rules      | Retired with the old host-level routes. Current cluster wildcard DNS points through Tailscale; Redlib retains its separate Control D resolver identifier.                   |
| HAOS public webhook           | A suspended `HTTPRoute` preserves only `/api/webhook` on `home-assistant.excloo.com`; its selectorless Service targets the substrate-owned HAOS address with validated TLS. |
| Homepage external targets     | Gatus, HAOS add-ons, Netboot, Syncthing, TrueNAS, and UniFi use explicit current substrate addresses. Provider bookmarks are retained.                                      |
| OAuth2 forward authentication | Retired with Dozzle and the old Traefik dashboard. No remaining route consumes OAuth2 Proxy.                                                                                |
| Redlib Cloudflare WAF         | A suspended `RedlibWAFPolicy` discovers the zone, adopts the legacy JS challenge, masks its monitoring token, and preserves unrelated phase rules.                          |
| Redlib defaults               | The legacy subscriptions and settings are retained exactly; the accidental `sideproject` substitution is removed.                                                           |
| Resend keys                   | Beszel, BookOrbit, Immich, Linkwarden, and Pocket ID use sending-only `ResendKey` resources. Retained Gatus and its deployed secret remain bounded to `homelab-fly`.        |
| Shelfarr                      | Shelfmark replaces it and retains the books integration, Byparr dependency, and Pocket ID contract.                                                                         |

The B2 and Cloudflare controllers remain suspended until their least-privilege
bootstrap items exist and their first observations have been reviewed. See
[`external-automation.md`](external-automation.md).

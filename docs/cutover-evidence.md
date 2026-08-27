# Live Migration Evidence

This record separates repository implementation from evidence observed on live
clusters. Update it after each reconciliation, cutover, rollback-window review,
or retirement action.

## Snapshot: 27 August 2026

Read-only checks at 03:53 AEST observed both clusters at Git revision
`13de52ae653ce55a317e57c1587dafa65ce3b9ee` (`Remove completed Windmill
migration`). This is the committed `HEAD`; the current migration worktree is not
yet represented in either cluster.

| Evidence               | `mbk` | `syd` |
| ---------------------- | ----- | ----- |
| Application inventory  | Ready | Ready |
| Foundation inventory   | Ready | Ready |
| Helm releases Ready    | 31    | 14    |
| Non-ready running Pods | 0     | 0     |
| Platform inventory     | Ready | Ready |
| Root inventory         | Ready | Ready |

### Automation and Data

- All live External Secrets report `Ready=True`; both `onepassword`
  `ClusterSecretStore` resources report `Valid`.
- Beszel, BookOrbit, Immich, and Linkwarden each have a live `ResendKey` and
  provider-http `Request` reporting `Ready=True` and `Synced=True`.
- The latest 1Password item reconciliation succeeded on both clusters and was
  idempotent: `mbk` reconciled 19 items with zero changes and `syd` reconciled
  six items with zero changes.
- BookOrbit, Immich, Linkwarden, Miniflux, and Windmill each have one healthy
  CloudNativePG instance. No PersistentVolumeClaim is unbound.
- The retained-NFS logical backup Jobs for BookOrbit, Immich, Linkwarden, and
  Miniflux completed successfully on their latest observed schedules.

### Repository Preflight

Flux server-side dry-runs against both live foundation inventories show that
the bridge revision will actively move OnePassword Connect from `platform` to
`foundation` and add `kustomize.toolkit.fluxcd.io/prune: disabled` before the
dependent platform reconciliation drops its old inventory entries.
VictoriaMetrics alone uses `IfNotPresent` in the old foundation inventory while
the new platform owner adopts it. Regression tests enforce that distinction,
the `platform` dependency on `foundation`, and preservation of the live Helm
install and upgrade retries.

The automation dry-run accepts the new provider configurations, composite
definitions, and B2 Requests. Resources in namespaces or APIs created by the
same unreconciled revision cannot complete a live server-side dry-run until
those prerequisites exist. Their rendered schemas and safety invariants pass
the repository check; live readiness remains a post-reconciliation gate.

All five staged workloads have suspended releases, private-only route parents,
no ExternalDNS opt-in, and no active schedule. In particular, RoMM's logical
backup remains suspended until a restored database produces a manually
validated dump.

### Route and Traffic Evidence

Every live Gateway reports healthy listener conditions. All routes except
`linkwarden/linkwarden-private` report `Accepted=True` and `ResolvedRefs=True`.
The rejected route reports `NotAllowedByListeners`; its namespace lacks the
declared private-access label. The current worktree corrects that label and adds
a regression test.

Sanitised Traefik access-log aggregates for the preceding 24 hours contained
live traffic for every public migrated application:

| Hostname               | Requests | Downstream statuses                    |
| ---------------------- | -------: | -------------------------------------- |
| `anisette.excloo.com`  |    1,330 | 1,327 × 200; 3 × 404                   |
| `books.excloo.com`     |       88 | 87 × 200; 1 × 404                      |
| `larapaper.excloo.com` |       84 | 84 × 200                               |
| `links.excloo.com`     |       68 | 68 × 200                               |
| `photos.excloo.com`    |      158 | 158 × 200                              |
| `reddit.excloo.com`    |    1,523 | 878 × 200; 3 × 302; 641 × 404; 1 × 500 |
| `shelf.excloo.com`     |       69 | 69 × 200                               |

Direct client checks returned expected 2xx or 3xx responses for every listed
`mbk` route except the rejected Linkwarden private route. Anisette responded on
`syd`; a non-browser Redlib request was challenged while its access log still
showed successful application traffic.

This evidence advances Anisette, Redlib, and Shelfmark from Reconciled to Cut
over. OpenSpeedTest advances from Implemented to Reconciled because both Flux
inventories, workloads, and routes are healthy; it does not advance to Cut over
until the `syd` wildcard is repaired and traffic is observed through both
private routes. Byparr and Homepage remain Reconciled because these checks did
not establish sustained consumer or user traffic.

## Open Gates

### Reconcile the Current Worktree

The worktree must be reviewed, committed, pushed, and reconciled before its new
applications, automation, ownership transfers, and route corrections can
produce live evidence. Do not apply rendered resources manually; Flux remains
the sole routine deployer.

### Repair the `syd` Wildcard Target

The Tailscale proxy for the private `syd` Gateway is healthy and online at
`100.98.254.8`, but `*.syd.excloo.dev` resolves to stale address
`100.113.199.91`. Consequently Headlamp, Grafana, and OpenSpeedTest time out from
the tailnet even though their workloads and routes are Ready.

The wildcard is substrate-owned. In `homelab`, run `mise run plan`, confirm that
the wildcard update is present, and do not accept destructive or unrelated
changes. Review the complete plan, then run `mise run apply` and review the exact
plan it presents before confirming. Recheck A and AAAA resolution and all three
private routes afterwards. Do not transfer the wildcard to ExternalDNS.

### Complete Rollback Windows

Accepted route transitions for the cut-over workloads range from Bifrost on 24
August 2026 at 08:48 UTC through Immich on 26 August 2026 at 07:46 UTC. No
rollback window is complete at this snapshot: the first individual window can
close on 31 August and the last on 2 September. Anisette, Redlib, and Shelfmark
were accepted on 25 August at approximately 05:54 UTC and cannot close before 1
September at approximately 05:54 UTC. A healthy resource or successful request
does not close a rollback window. Recheck each cut-over workload after seven
full days, confirm no unresolved regression, record the evidence, and only then
remove its previous delivery definition.

# Pocket ID Migration

Pocket ID is the final workload migration because every retained OIDC client
depends on it. The committed release, export schedules, and restore template are
suspended. Its route attaches only to the private Gateway when the release is
first enabled, so restoring or testing the application does not change the live
public route.

## Data and credential contract

Pocket ID 2.14.0 uses CloudNativePG PostgreSQL 18.6. Uploaded files use Pocket
ID's `database` backend, so the database and an application-native export form
a complete recovery unit. SQLite must not be placed on NFS.

The `Excloo ID` 1Password item supplies the existing encryption key, the Resend
SMTP key, and the static automation API key. The workload-item reconciler may
adopt `Excloo ID (pocket-id)` or `pocket-id`, then performs these value-preserving
field migrations:

| Legacy field     | Kubernetes-owned field |
| ---------------- | ---------------------- |
| `encryption_key` | `encryption-key`       |
| `mail_password`  | `api-key-resend`       |
| `static_api_key` | `static-api-key`       |

The migration copies each value and retains the legacy field while the previous
deployment remains a rollback option. Remove the legacy fields only after the
seven-day window closes and the previous delivery configuration is retired.

Grafana continues to use its cluster-local administrator credential on both
clusters. A retained Pocket ID client does not grant the cluster deployment
authority to adopt its secret unless that integration is explicitly restored
later.

It generates only a missing database password, encryption key, or static API
key. Do not enable Pocket ID unless reconciliation evidence shows that the
existing encryption key was adopted. A newly generated encryption key cannot
decrypt a restored database.

The static API key authenticates Crossplane only. It is not the human recovery
credential. The restored administrator and passkey remain the break-glass path
and must work without any downstream OIDC client.

## Identity automation

The `PocketIDClient` resource is deliberately narrow. It composes standard
provider-http Requests that observe and update an existing client and its group
access. It cannot create or delete a client, so a failed restore is visible and
cannot silently replace a client secret. Group Requests reconcile the named
`all_services` and `books` groups and may create a missing group, but cannot
delete one. User membership remains a human identity decision.

The retained client declarations are:

- Actual Budget
- Beszel
- BookOrbit
- Grafana
- Immich
- Linkwarden
- Miniflux
- Open WebUI
- Papra
- RoMM
- Shelfmark

These declarations and the group Requests reconcile through the separate
`pocket-id-automation` Flux Kustomization after applications. That
Kustomization does not wait for API readiness while Pocket ID is deliberately
suspended. This prevents staged identity work from masking the health of
unrelated applications; it does not relax the activation gate below.

## Restore procedure

Use a complete Pocket ID export from the previous deployment. Place the
reviewed ZIP on the `backup` PVC and record its SHA-256 digest. The old
deployment must remain available for rollback but must not run concurrently
with the restored authority.

1. Reconcile the namespace, External Secrets, database, and suspended Jobs.
2. Confirm that `Excloo ID` was adopted and that both Pocket ID External Secrets
   are Ready. Compare a digest of the materialised encryption key with the
   previous deployment without printing the key.
3. Confirm that the database is Ready and the Pocket ID HelmRelease remains
   suspended.
4. Generate a Job manifest from `cronjob/pocket-id-restore` with
   `kubectl create job --from=cronjob/pocket-id-restore`, using
   `--dry-run=client -o yaml`. Before applying it, set `RESTORE_ARCHIVE` to the
   exact `/backup/pocket-id-*.zip` path and `RESTORE_SHA256` to its reviewed
   digest.
5. Review the complete Job manifest, apply it, and retain its logs. The Job
   rejects other paths, verifies both the digest and ZIP structure, imports
   without forcing the upstream exclusive lock, then makes and verifies a new
   export from the restored database.
6. Enable the HelmRelease through Git. Keep the route on the private Gateway.
   Confirm health, discovery metadata, administrator passkey login, mail, users,
   groups, and all eleven OIDC clients. Every `PocketIDClient` and provider-http
   Request must become Ready.
7. Run one manual database backup and one complete export Job. Validate the
   custom-format dump with `pg_restore --list` and the ZIP with `unzip -t`, then
   restore the ZIP into a disposable database before enabling both schedules.

The restore Job is destructive by design, remains suspended, defaults both
required inputs to empty strings, and has no force-lock option. Never run it
against the active authority.

## Cutover and rollback

Public cutover is a separate reviewed Git change. Change the route parent from
`private` to `public-tunnel`, add the public-access label to the route and
namespace, and opt the route into proxied ExternalDNS. Observe discovery,
authorisation, token exchange, mail, and gateway logs before stopping the old
deployment.

Keep the old deployment stopped but recoverable for seven days. Roll back by
restoring its route and restarting it with the unchanged encryption key. Keep
the final Pocket ID ZIP, PostgreSQL dump, retained NFS backup PVC, TrueNAS
snapshot, and cutover evidence until the rollback window closes.

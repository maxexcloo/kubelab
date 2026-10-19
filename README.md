# Kubelab

Kubernetes workloads and application integrations managed through Flux and
Kustomize. The repository contains the desired configuration, validation tools
and deployment tasks.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is unavailable.

The shared `minilab` repository owns mini-app source and workload manifests.
Kubelab selects its Flux entry point and supplies shared integration settings.

Read the owning configuration for current placement, endpoints, storage and
credentials. The README describes general workflows; `AGENTS.md` contains project
invariants and editing conventions.

## Repository Layout

- `apps/`: workload bases, integration declarations and cluster overlays.
- `clusters/`: Flux entry points and cluster-specific configuration.
- `platform/`: shared controllers, sources and automation implementations.
- `scripts/`: bootstrap, rendering and validation commands.
- `tests/`: focused configuration and integration checks.

## Setup

Install the [shared Mise configuration](https://github.com/maxexcloo/dotfiles#shared-tools--tasks)
before running local Mise tasks.

Install jq, wget and [Mise](https://mise.jdx.dev/), then install the configured tools
and Git hooks:

```shell
mise trust
mise run setup
mise run check
```

Deployment requires a kubeconfig context matching the selected configuration in
`clusters/`. Credentials, kubeconfigs and rendered Secrets stay outside Git.

## Configuration Changes

Edit workload configuration in `apps/base/<application>` and select it through
`apps/overlays/<cluster>`; `AGENTS.md` describes the editing conventions. Local
manifest checks cover Kustomize output, so render changed Helm charts separately.

## Deployment

Merge reviewed pull requests into `main`; Flux reconciles it automatically.
Use the deployment task to fetch and reconcile immediately. Select an existing
cluster and optionally a configured reconciliation component.

| Command                                   | Purpose                                                              |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `mise run bootstrap <cluster>`            | Install networking, bootstrap credentials and start Flux             |
| `mise run check`                          | Validate manifests, metadata, formatting, scripts and reconciliation |
| `mise run deploy <cluster> [component]`   | Fetch Git and reconcile the entry point or selected component        |
| `mise run fmt`                            | Format project files                                                 |
| `mise run setup`                          | Install configured tools and Git hooks                               |
| `mise run status <cluster> [application]` | Show reconciliation status or watch an application's Helm release    |

Bootstrap is a separate operation after infrastructure provisioning; routine
application upgrades do not require it. The deploy task waits for its selected
reconciliation stage. Check the affected release and application separately to
verify the workload has recovered and its important workflow works.

CI validates changes and refreshes external monitoring through the configured
delivery workflow. Flux performs routine cluster deployments.

## Updates & Recovery

PostgreSQL uses the CloudNativePG Barman plugin for online S3 backups and WAL
archiving. App-state jobs briefly stop their application, copy selected volumes,
resume it and upload the copy with Restic. Schedules, retention and volume
selection live beside their owning resources. Dedicated TrueNAS app datasets,
bulk media and caches are excluded.

Credentials and Restic encryption passwords stay in 1Password. Restore PostgreSQL
through the Barman plugin and app state through Restic into fresh volumes before
switching the workload. Initial backup uploads are verified separately from restore
tests.

Check upstream migration requirements before upgrading. Preserve persistent data
and the credentials needed to restore it. Reverting an image does not reverse a
database migration. External-resource deletion and credential archival follow
their owning declarations; removing a workload does not necessarily delete its
external resources.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

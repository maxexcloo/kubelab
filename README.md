# Kubelab

Kubernetes workloads and application integrations for my homelab, managed with
Flux and Kustomize. This repository has the desired configuration, the validation
tools and the deployment tasks.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is down.

Mini-app source and workload manifests live in the shared `minilab` repository.
Kubelab picks its Flux entry point and supplies the shared integration settings.

Current placement, endpoints, storage and credentials are in the configuration
that owns them. This README covers the general workflows, and `AGENTS.md` has the
project invariants and editing conventions.

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

Deploying needs a kubeconfig context that matches the selected configuration in
`clusters/`. Credentials, kubeconfigs and rendered Secrets stay out of Git.

## Configuration Changes

Edit workload configuration in `apps/base/<application>` and select it through
`apps/overlays/<cluster>`. `AGENTS.md` describes the editing conventions. Local
manifest checks only cover Kustomize output, so render changed Helm charts
separately.

## Deployment

Merge reviewed pull requests into `main` and Flux reconciles them automatically.
To fetch and reconcile straight away, use the deploy task with an existing
cluster and the affected application. Verification checks the exact remote `main`
revision, the HelmRelease generation and its workload rollouts. Supply a full
commit SHA to verify a particular merge; a superseding revision fails explicitly.
For releases in a different namespace, use `namespace/release` as the application.

| Command                                              | Purpose                                                              |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `mise run bootstrap <cluster>`                       | Install networking, bootstrap credentials and start Flux             |
| `mise run check`                                     | Validate manifests, metadata, formatting, scripts and reconciliation |
| `mise run deploy <cluster> <application> [revision]` | Fetch Git, reconcile apps and verify the selected workload           |
| `mise run fmt`                                       | Format project files                                                 |
| `mise run setup`                                     | Install configured tools and Git hooks                               |
| `mise run status <cluster> [application]`            | Show reconciliation status or watch an application's Helm release    |

Bootstrap is a separate step after infrastructure provisioning, and routine
application upgrades don't need it. Delivery waits for the affected application
without waiting for unrelated releases. The reported duration measures the
verification command, not merge-to-readiness time. Check the application's main
workflow separately.

CI validates changes and refreshes external monitoring through the configured
delivery workflow. Flux handles routine cluster deployments.

## Updates & Recovery

PostgreSQL uses the CloudNativePG Barman plugin for online S3 backups and WAL
archiving. App-state jobs briefly stop their application, copy the selected
volumes, start it again and upload the copy with Restic. Schedules, retention and
volume selection sit beside the resources they belong to. Dedicated TrueNAS app
datasets, bulk media and caches aren't backed up.

Credentials and Restic encryption passwords stay in 1Password. Restore PostgreSQL
through the Barman plugin, and app state through Restic, into fresh volumes before
switching the workload over. The first backup uploads are checked separately from
restore tests.

Check upstream migration requirements before upgrading. Keep persistent data and
the credentials needed to restore it. Rolling back an image doesn't undo a
database migration. Deleting external resources and archiving credentials follow
their own declarations, so removing a workload doesn't necessarily delete its
external resources.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

# Kubelab

Kubernetes workloads and application integrations for my homelab, managed with
Flux and Kustomize.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is down.

Mini-app source and workload manifests live in the shared `minilab` repository.
Kubelab picks its Flux entry point and supplies the shared integration settings.

Current placement, endpoints, storage and credentials are in the configuration
that owns them. `AGENTS.md` has the project invariants and editing conventions.

## Setup

Install the [shared Mise configuration](https://github.com/maxexcloo/dotfiles#shared-tools--tasks)
before running local Mise tasks.

Install wget and [Mise](https://mise.jdx.dev/), then install the configured tools
and Git hooks:

```shell
mise install
mise run setup
mise run check
```

Deploying needs a kubeconfig context that matches the selected configuration in
`clusters/`. Credentials, kubeconfigs and rendered Secrets stay out of Git.

## Configuration Changes

Edit workload configuration in `apps/base/<application>` and select it through
`apps/overlays/<cluster>`. Local manifest checks cover what Flux builds, including
its variable substitutions, but not Helm output, so render changed Helm charts
separately.

## Syncthing

Manage Syncthing peers and folder settings in each instance's GUI. The `AI`
folder syncs both ways between Venus and Saturn and ignores `*.download`, `*.part`
and `*.part.json`; keep Ignore Permissions on at Saturn to preserve its ACLs.

## Deployment

Merge reviewed pull requests into `main` and Flux reconciles them automatically.
To reconcile straight away and verify the application at the merged revision,
use the deploy task with an existing cluster and the affected application. For
releases in a different namespace, use `namespace/release` as the application.

| Command                                              | Purpose                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| `mise run bootstrap <cluster>`                       | Install networking, bootstrap credentials and start Flux          |
| `mise run check`                                     | Validate manifests, metadata, formatting, scripts and tests       |
| `mise run deploy <cluster> <application> [revision]` | Fetch Git, reconcile apps and verify the selected workload        |
| `mise run fmt`                                       | Format project files                                              |
| `mise run setup`                                     | Install Git hooks                                                 |
| `mise run status <cluster> [application]`            | Show reconciliation status or watch an application's Helm release |

Bootstrap is a separate step after infrastructure provisioning; routine
application upgrades don't need it.

## Updates & Recovery

PostgreSQL backups use the CloudNativePG Barman plugin; app-state backups use
Restic and briefly stop the application. Schedules, retention and volume selection
sit beside the resources they belong to. Dedicated TrueNAS app datasets, bulk
media and caches aren't backed up.

Credentials and Restic encryption passwords stay in 1Password. Restore PostgreSQL
through the Barman plugin, and app state through Restic, into fresh volumes before
switching the workload over. A successful backup upload does not verify recovery;
test restores separately.

Check upstream migration requirements before upgrading. Keep persistent data and
the credentials needed to restore it. Rolling back an image doesn't undo a
database migration. Deleting external resources and archiving credentials follow
their own declarations, so removing a workload doesn't necessarily delete its
external resources.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

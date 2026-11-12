# Kubelab

Kubernetes workloads and application integrations for my homelab, managed with
Flux and Kustomize.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is down. Mini-app source and manifests live
in the `minilab` repository.

## Setup

Install wget and the [shared Mise configuration](https://github.com/maxexcloo/dotfiles#shared-tools--tasks),
then install the configured tools and Git hooks:

```shell
mise install
mise run setup
mise run check
```

Deploying needs a kubeconfig context that matches the selected configuration in
`clusters/`.

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

Restore PostgreSQL through the CloudNativePG Barman plugin, and app state through
Restic, into fresh volumes before switching the workload over. Dedicated TrueNAS
app datasets, bulk media and caches aren't backed up.

Check upstream migration requirements before upgrading; rolling back an image
doesn't undo a database migration.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

# Kubelab

Kubernetes workloads and application integrations for my homelab, managed with
Flux and Kustomize.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is down. Mini-app source and manifests live
in the `minilab` repository.

## Setup

Install the [shared Mise configuration](https://github.com/maxexcloo/dotfiles#shared-tools--tasks),
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
`apps/overlays/<cluster>`.

## Syncthing

Manage Syncthing peers and folders in each instance's GUI. Keep Ignore Permissions
on at Saturn to preserve its ACLs.

## Deployment

Merge reviewed pull requests into `main` and Flux reconciles them automatically.
To reconcile straight away and verify the application at the merged revision,
use the deploy task with an existing cluster and the affected application. For
releases in a different namespace, use `namespace/release` as the application.

| Command                                              | Purpose                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| `mise run bootstrap <cluster>`                       | Install networking, bootstrap credentials and start Flux          |
| `mise run check`                                     | Validate manifests, metadata, formatting, scripts and tests       |
| `mise run deploy <cluster> <application> [revision]` | Reconcile and verify the workload and its owning Kustomization    |
| `mise run fmt`                                       | Format project files                                              |
| `mise run setup`                                     | Install Git hooks                                                 |
| `mise run status <cluster> [application]`            | Show reconciliation status or watch an application's Helm release |

Bootstrap is a separate step after infrastructure provisioning; routine
application upgrades don't need it.

## Updates & Recovery

Restore PostgreSQL through the CloudNativePG Barman plugin, and app state through
Restic, into fresh volumes before switching the workload over. If Saturn is
unavailable, recover the S3 backup dataset and any app datasets the workload
needs from Pluto's ZFS replicas. Saturn's replication excludes the AI, games
and Time Machine datasets.

Check upstream migration requirements before upgrading; rolling back an image
doesn't undo a database migration.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

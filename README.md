# Kubelab

Kubernetes workloads and application integrations managed through Flux and
Kustomize. The repository contains the desired configuration, validation tools
and deployment tasks.

## Ownership

This repository owns in-cluster controllers, workloads, routes, application DNS
and app-scoped integrations. `homelab` owns the infrastructure needed to rebuild
or reach a cluster while Kubernetes is unavailable.

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

Install jq, wget and [Mise](https://mise.jdx.dev/), then install the pinned tools
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
`apps/overlays/<cluster>`. Keep cluster differences in overlays. Helm releases and
native application settings belong beside their application; shared settings and
controllers belong under `platform/`.

Define settings once near their owner and use Kustomize replacements for derived
values. Preserve native configuration formats and upstream interfaces. Keep
substantial application configuration and executable code in their own files.

Validate the changed configuration before committing. Render changed Helm charts
separately: manifest checks cover Kustomize output, not chart-generated workloads.
Review deletion and recovery behaviour before removing declarations or changing
storage, secrets or external integrations.

## Deployment

Push reviewed changes to `main`; Flux reconciles the repository automatically.
Use the deployment task to fetch and reconcile immediately. Select an existing
cluster and optionally a configured reconciliation component.

| Command                                   | Purpose                                                              |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `mise run bootstrap <cluster>`            | Install networking, bootstrap credentials and start Flux             |
| `mise run check`                          | Validate manifests, metadata, formatting, scripts and reconciliation |
| `mise run deploy <cluster> [component]`   | Fetch Git and reconcile the entry point or selected component        |
| `mise run fmt`                            | Format project files                                                 |
| `mise run setup`                          | Install pinned tools and Git hooks                                   |
| `mise run status <cluster> [application]` | Show reconciliation status or watch an application's Helm release    |

Bootstrap is a separate operation after infrastructure provisioning; routine
application upgrades do not require it. The deploy task waits for its selected
reconciliation stage. Check the affected release and application separately to
verify the workload has recovered and its important workflow works.

CI validates changes and refreshes external monitoring through the configured
delivery workflow. Flux performs routine cluster deployments.

## Updates & Recovery

Use Renovate's dependency dashboard to review pending updates. Update schedules
and grouping are configured in `renovate.json`; merges remain manual.

Check upstream migration requirements before upgrading. Preserve persistent data
and the credentials needed to restore it. Reverting an image does not reverse a
database migration. External-resource deletion and credential archival follow
their owning declarations; removing a workload does not necessarily delete its
external resources.

## Licence

AGPL-3.0 — see [LICENSE](LICENSE).

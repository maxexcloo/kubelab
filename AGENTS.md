# AGENTS.md

## Project Overview

This repository owns Kubernetes resources reconciled by Flux and app-scoped
integrations. `README.md` describes purpose and general usage; owning
configuration records current deployment details. The separate `homelab`
repository owns everything required to rebuild or reach a cluster while
Kubernetes is unavailable.

The `mini-apps` repository owns mini-app source and native workload manifests.
Kubelab owns its Flux source, cluster selection and shared integration settings.

## Conventions

- Read the owning configuration before changing architecture, ownership,
  deletion behaviour, networking, storage or secrets.
- Treat app and cluster configuration as authoritative for current workload
  ownership and `homelab` configuration as authoritative for substrate details.
- Omit trailing slashes from project-owned base URLs.
- Prefer upstream Helm charts, then `bjw-s/app-template`, then direct manifests.
- Keep cluster differences in overlays; do not copy an entire application.
- Pin tools, charts, images, and remote manifests to stable release versions.
  Use readable major tags such as `v7` for GitHub Actions, not commit SHAs.
  Updatecli previews upgrades locally for manual review.
- Keep credentials, kubeconfigs, and rendered Secret values out of Git.
- Default Crossplane external resources to orphan-on-delete.
- Do not change a live route without explicit approval and a reviewed plan.

## File Organisation

- `apps/`: workload bases and cluster overlays.
- `clusters/`: Flux entry points for each cluster.
- `platform/`: cluster controllers and shared configuration.

Private browser and API routes include `<app>.<cluster>.excloo.dev` alongside
existing primary addresses. App-template routes derive aliases through the shared
route transformers; upstream charts use their native route shape. Keep aliases
on private gateways. Database-backed application pods use required affinity to
the CloudNativePG primary in their namespace; local volumes remain authoritative
for data placement. Node network labels describe host locality, independently of
application access. Cluster applications default to internal nodes; cluster
overlays select external workloads. Public routes on external nodes attach to the
`public-direct` gateway, so Cloudflare reaches the origin on its public address;
routes whose origin is behind NAT attach to the `public-tunnel` gateway. Mini apps
use only `<name>.mini.excloo.com`.

Keep app-specific configuration and integration declarations beside the app. Keep
shared controllers and integration implementations under `platform/`.

Use standard Kubernetes configuration directly. Do not add a general application
schema, generator, operator, or generated manifest. A narrow repository-defined
resource is acceptable when it materially removes repeated security or lifecycle
integration logic; document the contract in its schema and compose standard
resources underneath. Use Kustomize for composition and small patches. Use
`configMapGenerator` only to mount checked-in app configuration, scripts or assets;
do not use `secretGenerator`. Keep executable code in its own source file. Keep
shared chart policy in native Kustomize components and app-specific values in the
app's Flux `HelmRelease` patch; use overlay patches for cluster differences. The
`app-namespace` component derives app-local namespaces and Flux release identity
from the app's Namespace. The `application` component supplies standard probes,
security and scratch storage. Use `main` for its primary controller,
container and service; preserve deployed names and immutable selector labels.
Override only app differences; native patch `null` removes an inherited setting.
Specialised app-template workloads use the `workload` component without the
application defaults. Keep
databases, external secrets, integrations, namespaces, network policies and storage
in files named for their purpose rather than mixed `resources.yaml` files. Use
standard Kustomize replacements for derived hostnames and URLs. Homepage retains
its existing configuration layout and probe timings.

Keep root Markdown limited to `AGENTS.md` and `README.md`. Keep `README.md`
focused on purpose and general usage; do not duplicate deployment inventories,
application runbooks or instance-specific settings. Explain non-obvious behaviour
near its owning configuration. Do not add a `docs/` tree.

## Sorting Exceptions

Use conventional Kubernetes field and resource ordering. Keep project-owned
YAML free of blank separator lines.

For Homepage service dashboards, put widgets before other peer cards and
alphabetise within each group. Preserve deliberate grouping and workflow order.

## Style

- Add scheduled jobs or automatic deletion only when explicitly requested.
- Use supported app configuration interfaces; leave unsupported settings manual.
- Keep comments local and specific to non-obvious behaviour.
- Use 10-second probe intervals, 5-second timeouts and three consecutive failures;
  allow 30 failures for startup. Preserve app-specific check mechanisms and
  endpoints, and retain chart limitations or evidenced exceptions.

## Verification

- Render changed Helm charts and use small response fixtures for changed API
  comparisons; avoid adding a general validation framework.

## Git History

Keep a decision or ownership transfer separate from its implementation when
review of that decision is useful.

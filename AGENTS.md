# AGENTS.md

## Project Overview

This repository owns Kubernetes resources reconciled by Flux and app-scoped
integrations. `README.md` describes purpose and general usage; owning
configuration records current deployment details. The separate `homelab`
repository owns everything required to rebuild or reach a cluster while
Kubernetes is unavailable.

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
  Renovate proposes upgrades for manual review.
- Keep credentials, kubeconfigs, and rendered Secret values out of Git.
- Default Crossplane external resources to orphan-on-delete.
- Do not change a live route without explicit approval and a reviewed plan.

## File Organisation

- `apps/`: workload bases and cluster overlays.
- `clusters/`: Flux entry points for each cluster.
- `platform/`: cluster controllers and shared configuration.

Keep app-specific configuration and integration declarations beside the app. Keep
shared controllers and integration implementations under `platform/`.

Use standard Kubernetes configuration directly. Do not add a general application
schema, generator, operator, or generated manifest. A narrow repository-defined
resource is acceptable when it materially removes repeated security or lifecycle
integration logic; document the contract in its schema and compose standard
resources underneath. Use Kustomize for composition and small patches. Use
`configMapGenerator` only to mount checked-in app configuration, scripts or assets;
do not use `secretGenerator`. Keep executable code in its own source file. Keep
chart values in the upstream Flux `HelmRelease` or its native app-local settings
patch. Use standard Kustomize replacements for derived hostnames and URLs.

Keep root Markdown limited to `AGENTS.md` and `README.md`. Keep `README.md`
focused on purpose and general usage; do not duplicate deployment inventories,
application runbooks or instance-specific settings. Explain non-obvious behaviour
near its owning configuration. Do not add a `docs/` tree.

## Sorting Exceptions

Use conventional Kubernetes field and resource ordering. Keep project-owned
YAML free of blank separator lines.

## Style

- Add scheduled jobs or automatic deletion only when explicitly requested.
- Use supported app configuration interfaces; leave unsupported settings manual.
- Keep comments local and specific to non-obvious behaviour.

## Verification

- Render changed Helm charts and use small response fixtures for changed API
  comparisons; avoid adding a general validation framework.

## Git History

Keep a decision or ownership transfer separate from its implementation when
review of that decision is useful.

# AGENTS.md

## Project Overview

This repository owns Kubernetes resources reconciled by Flux and app-scoped
integrations. `README.md` documents the current system. The separate `homelab`
repository owns everything required to rebuild or reach a cluster while
Kubernetes is unavailable.

## Conventions

- Read `README.md` before changing architecture, ownership, deletion behaviour,
  networking, storage or secrets.
- Treat `README.md` as authoritative for current workload ownership and
  `homelab` configuration as authoritative for substrate implementation
  details.
- Use Australian English in project-owned prose and identifiers.
- Use `.yaml`, not `.yml`, for project-owned YAML.
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
integration logic; document the contract in `README.md` and compose standard
resources underneath. Use Kustomize for composition and small patches. Use
`configMapGenerator` only to mount checked-in scripts or assets; do not use
`secretGenerator`. Keep executable code in its own source file. Keep chart values
directly in the upstream Flux `HelmRelease` that consumes them.

Keep root Markdown limited to `AGENTS.md` and `README.md`. Keep maintained
project documentation in `README.md`; do not add a `docs/` tree.

## Sorting Convention

Use conventional Kubernetes field and resource ordering. In other unordered
mappings, sort single-line values before objects, alphabetically within each;
keep list-item identifiers first. Preserve dependency, routing and procedural
order. Keep project-owned YAML free of blank separator lines.

Sort Mise tools and tasks within lifecycle sections, Renovate rules by description,
and Prek hooks by ID. Workflows start with `name`, `on`, `permissions`,
`concurrency`, then configuration and jobs. Sort unordered prose lists and tables.

## Style

- Prefer plain, direct Kubernetes manifests and upstream charts over abstractions
  and generic pipelines.
- Add scheduled jobs or automatic deletion only when explicitly requested.
- Use supported app configuration interfaces; leave unsupported settings manual.
- Keep comments local and specific; document only material operational behaviour
  in `README.md`.
- Keep check orchestration single-layered so the same validator is not run both
  directly and through a nested task in one path.

## Verification

- Run `mise run check` before handoff.
- Render changed Helm charts and use small response fixtures for changed API
  comparisons; avoid adding a general validation framework.
- Run `mise run prek` after changing hooks or workflows.

## Git History

Git history is the work log. Use small, imperative commit subjects. Keep a
decision or ownership transfer separate from its implementation when review of
that decision is useful.

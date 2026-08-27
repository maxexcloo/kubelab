# AGENTS.md

## Project Overview

This repository owns Kubernetes resources reconciled by Flux and app-scoped
integrations. `README.md` documents the current system, and `PLAN.md` contains
only unfinished work. The separate `homelab` repository owns everything
required to rebuild or reach a cluster while Kubernetes is unavailable.

## Conventions

- Read `README.md` before changing architecture, ownership, deletion behaviour,
  networking, storage or secrets. Read `PLAN.md` before resolving unfinished
  cross-repository work.
- Treat `README.md` as authoritative for current workload ownership,
  `PLAN.md` as authoritative for unfinished ordering, and `homelab`
  configuration as authoritative for substrate implementation details.
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

- `clusters/`: Flux entry points for each cluster.
- `apps/`: workload bases and cluster overlays.
- `platform/`: cluster controllers and shared configuration.

Use standard Kubernetes configuration directly. Do not add a general application
schema, generator, operator, or generated manifest. A narrow repository-defined
resource is acceptable when it materially removes repeated security or lifecycle
integration logic; document the contract in `PLAN.md` and compose standard
resources underneath. Use Kustomize only for composition and small patches; do
not use `configMapGenerator` or `secretGenerator`. Keep chart values directly in
the upstream Flux `HelmRelease` that consumes them.

Keep root Markdown limited to `AGENTS.md`, `README.md`, and `PLAN.md`. Keep
maintained project documentation in `README.md`; do not add a `docs/` tree.

## Sorting Convention

Sort unordered assignments in this order:

1. Single-line values, alphabetically by key.
2. Multi-line values, alphabetically by key.

Underscore-prefixed names sort before other names. Apply this recursively to
unordered project-owned YAML mappings, environment blocks, and template argument
objects. A non-empty object is multi-line. A scalar-only array is a single-line
value even when formatting wraps it; an array containing an object or array is
multi-line. Do not use blank separator lines in project-owned YAML. Preserve
blank lines in pinned upstream and generated manifests.

List-item identifiers come first in `type`, `name`, `id` order. Prek hook items
use `id`, then `name`; sort remaining fields normally.

Sort Mise tools alphabetically and tasks alphabetically within each lifecycle
section. Sort Renovate package rules by description and Prek hooks by `id`.
GitHub workflows use top-level `name`, `on`, `permissions`, `concurrency`, then
global configuration and `jobs`. Preserve dependency order within workflow
steps.

Sort unordered peer headings, lists, and table rows alphabetically. Preserve
API, schema, interface, procedural, dependency, routing, priority,
chronological, and other meaningful order. In particular, keep conventional
Kubernetes field and resource ordering instead of alphabetising it.

## Style

- Prefer plain, direct Kubernetes manifests and upstream charts over abstractions
  and generic pipelines.
- Keep comments local and specific; put operational explanations in `README.md`.
- Keep check orchestration single-layered so the same validator is not run both
  directly and through a nested task in one path.

## Verification

- Run `mise run check` before handoff.
- Run `mise run prek` after changing hooks or workflows.

## Git History

Git history is the work log. Use small, imperative commit subjects. Keep a
decision or ownership transfer separate from its implementation when review of
that decision is useful.

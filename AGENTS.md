# AGENTS.md

## Project Overview

This repository owns Kubernetes resources reconciled by Flux and app-scoped
integrations. The separate `homelab` repository owns everything required to
rebuild or reach a cluster while Kubernetes is unavailable.

## Conventions

- Read `PLAN.md` before changing architecture, ownership, deletion behaviour,
  networking, storage, secrets, or migration order.
- Treat `PLAN.md` as authoritative for cross-repository ordering and workload
  ownership, and `homelab/PLAN.md` as authoritative for that repository's
  substrate implementation details.
- Use Australian English in project-owned prose and identifiers.
- Use `.yaml`, not `.yml`, for project-owned YAML.
- Prefer upstream Helm charts, then `bjw-s/app-template`, then direct manifests.
- Keep cluster differences in overlays; do not copy an entire application.
- Pin every tool, chart, image, and remote manifest to an exact stable
  version. Renovate proposes upgrades for manual review.
- Keep credentials, kubeconfigs, and rendered Secret values out of Git.
- Default Crossplane external resources to orphan-on-delete.
- Do not change a live route without explicit approval and a reviewed plan.

## File Organisation

- `clusters/`: Flux entry points for each cluster.
- `apps/`: workload bases and cluster overlays.
- `platform/`: cluster controllers and shared configuration.

Use standard Kubernetes configuration directly. Do not add a custom application
schema, generator, operator, generated manifest, or repository-defined resource
type. Use Kustomize only for composition and small patches; do not use
`configMapGenerator` or `secretGenerator`. Keep chart values directly in the
upstream Flux `HelmRelease` that consumes them.

Keep root Markdown limited to `AGENTS.md`, `README.md`, and `PLAN.md`. Put later
operational documentation under `docs/`.

## Verification

- Run `mise run check` before handoff.
- Run `mise run prek` after changing hooks or workflows.

## Git History

Git history is the work log. Use small, imperative commit subjects. Keep a
decision or ownership transfer separate from its implementation when review of
that decision is useful.

# AGENTS.md

## Project Overview

This repository is the source of truth for the Talos Kubernetes homelab. Flux
owns Kubernetes reconciliation. OpenTofu under `tofu/` owns only the substrate
and bootstrap resources documented in `plan.md`.

## Conventions

- Read `plan.md` before changing architecture, ownership, deletion behaviour,
  networking, storage, secrets, or migration order.
- Use Australian English in project-owned prose and identifiers.
- Use `.yaml`, not `.yml`, for project-owned YAML.
- Prefer upstream Helm charts, then `bjw-s/app-template`, then direct manifests.
- Keep cluster differences in overlays; do not copy an entire application.
- Pin every tool, chart, image, provider, and remote manifest to an exact stable
  version. Renovate proposes upgrades for manual review.
- Keep credentials, Talos secrets, kubeconfigs, OpenTofu plans, and generated
  Secret values out of Git.
- Use stable semantic keys for OpenTofu `for_each`; never use list indexes for
  resource identity.
- Default Crossplane external resources to orphan-on-delete.
- Do not run `tofu apply`, reset a host, bootstrap etcd, or change a live route
  without explicit approval and a reviewed plan.

## File Organisation

- `catalogue/`: application metadata and schema.
- `clusters/`: Flux entry points for each cluster.
- `apps/`: workload bases and cluster overlays.
- `platform/`: cluster controllers and shared configuration.
- `talos/`: non-secret machine configuration patches and operator guidance.
- `tofu/`: independently initialised substrate stacks.
- `generated/`: deterministic artefacts derived from the catalogue.
- `scripts/`: small validation and generation programs.

Keep root Markdown limited to `AGENTS.md`, `README.md`, and `plan.md`. Put later
operational documentation under `docs/`.

## Verification

- Run `mise run check` before handoff.
- Run `mise run prek` after changing hooks or workflows.
- Run `mise run plan` only immediately before a requested infrastructure review.
- Apply exactly a saved and reviewed OpenTofu plan; never apply an unreviewed
  refresh.

## Git History

Git history is the work log. Use small, imperative commit subjects. Keep a
decision or ownership transfer separate from its implementation when review of
that decision is useful.

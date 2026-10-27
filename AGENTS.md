# AGENTS.md

## Project Overview

This repository owns the Kubernetes resources reconciled by Flux: app bases and
cluster overlays in `apps/`, Flux entry points in `clusters/`, and cluster
controllers and shared configuration in `platform/`. `README.md` describes
purpose and usage. The separate `homelab` repository owns the substrate that
rebuilds or reaches a cluster while Kubernetes is unavailable, and `minilab`
owns mini-app source. Actual Up keeps its dependencies, serial operation queue,
schedules and encrypted settings in its own repository; Kubelab deploys its
published image.

## Conventions

- Read the owning configuration before changing architecture, ownership,
  deletion behaviour, networking, storage or secrets.
- Treat app and cluster configuration as authoritative for current workload
  ownership and `homelab` configuration as authoritative for substrate details.
- Prefer upstream Helm charts, then `bjw-s/app-template`, then direct manifests.
- Keep cluster differences in overlays; do not copy an entire application.
- Upgrade Flux manually with `flux install --export`; Renovate ignores
  `gotk-components.yaml`.
- Routes alias `onepassword.excloo.dev/item` to their `gethomepage.dev/name`,
  optionally with a bracketed qualifier that the card's location tag already
  shows. Renaming a 1Password item is a coordinated change: rename it in
  1Password and every reference together.
  Keep Kubernetes resource identities independent of item titles.
- Publish generated credentials to 1Password with PushSecrets. Confidential
  PocketIDClients name the item that receives their generated
  `oidc-client-secret`; never copy client secrets by hand. Each PocketIDClient
  admits the `all_services` group and its own group, named after the client;
  group membership is managed in Pocket ID, not in this repository.
- Minilab reconciles as `flux-system/minilab`; its admission policy limits it to
  namespaces it creates and items titled `Minilab: <App>`. Grant it new kinds in
  `apps/base/minilab` before mini apps use them.
- Default Crossplane external resources to orphan-on-delete.
- Do not change a live route without explicit approval and a reviewed plan.

## File Organisation

- `apps/`: workload bases and cluster overlays.
- `clusters/`: Flux entry points for each cluster.
- `platform/`: cluster controllers and shared configuration.

### Routing & Placement

- Private browser and API routes include `<app>.<cluster>.excloo.dev` alongside
  existing primary addresses. Keep aliases on private gateways.
- The shared route transformers add the alias to app-template routes;
  hand-written routes list `<app>.${cluster_name}.excloo.dev` themselves.
- Public routes on external nodes attach to the `public-direct` gateway once the
  zone reaches origins over HTTPS (Cloudflare SSL/TLS mode Full), so Cloudflare
  connects to the public address instead of the tunnel. Routes whose origin is
  behind NAT attach to the `public-tunnel` gateway.
- Mini apps use only `<name>.mini.excloo.com`.
- Cluster applications default to internal nodes; cluster overlays select
  external workloads. Node network labels describe host locality, independently
  of application access.
- Database-backed application pods use required affinity to the CloudNativePG
  primary in their namespace; local volumes remain authoritative for data
  placement.
- SQLite apps use one replica, the `Recreate` strategy and local volumes, never
  NFS.

### Composition

- Keep app-specific configuration and integration declarations beside the app.
  Keep shared controllers and integration implementations under `platform/`.
- Use standard Kubernetes configuration directly. Do not add a general application
  schema, generator, operator, or generated manifest. A narrow repository-defined
  resource is acceptable when it materially removes repeated security or lifecycle
  integration logic; document the contract in its schema and compose standard
  resources underneath.
- The 1Password item reconciler in `platform/secrets/onepassword-items` is the
  approved narrow exception: a scheduled job that updates referenced items and
  prunes unreferenced fields and archives unreferenced Kubelab-tagged items. Its
  contract lives beside it.
- Use Kustomize for composition and small patches. Use `configMapGenerator` only
  to mount checked-in app configuration, scripts or assets; do not use
  `secretGenerator`. Keep executable code in its own source file.
- Flux `postBuild` substitution rewrites `${...}` in everything it applies,
  ConfigMaps included. Mark mounted scripts and assets
  `kustomize.toolkit.fluxcd.io/substitute: disabled`.
- Keep shared chart policy in native Kustomize components and app-specific values
  in the app's Flux `HelmRelease` patch; use overlay patches for cluster
  differences.
- Each app kustomization sets its native `namespace:` and names its resources
  literally; shared components name their resources after the app's Namespace.
  Resources in another namespace derive it from what references them, and
  Pocket ID clients stay cluster-scoped. The `application` component supplies
  standard probes, security and scratch storage. Specialised app-template
  workloads use the `workload` component without the application defaults.
- Use `main` for the primary controller, container and service; preserve deployed
  names and immutable selector labels. Override only app differences; native
  patch `null` removes an inherited setting.
- Keep databases, external secrets, integrations, namespaces, network policies
  and storage in files named for their purpose rather than mixed `resources.yaml`
  files.
- Homepage retains its existing configuration layout and probe timings.

### Shared Values

Define each value once:

- Settings shared across apps: `${variables}` that Flux substitutes, defined in
  `platform/settings/settings.yaml` (cross-cluster) and
  `clusters/<cluster>/settings/settings.yaml`. Consumers write the variable
  where they need it. Substitution is strict, so a missing variable fails the
  render and the reconciliation.
- A value with one consumer lives where it is used; cluster-specific files write
  it directly.
- App hostnames: the app's route. The shared route transformers derive its
  Homepage link, DNS record and Pocket ID client; Kustomize replacements in the
  app derive its own URL settings from `.invalid` placeholders, and the checks
  fail when one survives rendering.
- 1Password item titles: once per manifest, using YAML anchors for repeats.
- The app-template chart version: `platform/components/app-template`.
- Kubernetes client versions: Homelab's cluster data. Renovate groups the kubectl
  pins; merge them only once Homelab runs that Kubernetes version.

## Sorting Exceptions

Use conventional Kubernetes field and resource ordering. Keep project-owned
YAML free of blank separator lines.

For Homepage service dashboards, put widgets before other peer cards and
alphabetise within each group. Preserve deliberate grouping and workflow order.

## Style

- Use supported app configuration interfaces; leave unsupported settings manual.
- Use 10-second probe intervals, 5-second timeouts and three consecutive failures;
  allow 30 failures for startup. Preserve app-specific check mechanisms and
  endpoints, and retain chart limitations or evidenced exceptions.

## Verification & Delivery

- Render changed Helm charts and use small response fixtures for changed API
  comparisons; avoid adding a general validation framework.
- Deliver changes through a pull request; Flux deploys `main` once it merges.
  Verify the changed workload at the merged revision rather than waiting for
  unrelated workloads or a whole-cluster reconciliation.

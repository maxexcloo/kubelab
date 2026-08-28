# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## Reconciliation Blockers

1. Remove one of the two display-named `LaraPaper` items from the `mbk` cluster
   vault so External Secrets can select exactly one item. Force a refresh if
   required, then reconcile `apps`, `pocket-id-automation` and the cluster root
   at the current `main` revision. The retained application Secret remains
   present while reconciliation is blocked.
2. Extend the reviewed Homelab tailnet policy so only retained machine tags
   running Beszel agents can reach `tag:kubernetes:443`. Confirm the `syd` agent
   and retained standalone agents reconnect to `beszel.excloo.com`; `mbk` uses
   its cluster-local Service and must not depend on this lateral allowance.
3. Apply the current `homelab` `main` branch with its normal credentials to
   import the retained `home-assistant.excloo.com` record and reconcile the
   generic HAOS tunnel ingress. Confirm only `/api/webhook/.+` reaches Home
   Assistant, non-webhook paths use the `404` fallback and the record comment is
   `Homelab OpenTofu Managed`.

## External Automation

1. Review the existing Beszel B2 bucket and key settings, resume
   `clusters/mbk/b2-automation.yaml`, and require all three provider Requests to
   become Ready. Confirm the `B2ObjectStorage` claim reads the retained bucket
   name from `beszel-object-storage`, adopts exactly one `beszel` key with the
   fixed bucket-scoped capability profile and pushes only the access-key fields
   back to the `Beszel` item. The existing application key must remain unrotated;
   suspend the inventory if the bucket, key name, scope or capabilities differ.
2. Export the existing Cloudflare custom WAF phase, review the generated Redlib
   rule, resume `clusters/syd/cloudflare-automation.yaml`, and verify that the
   Gatus bypass, browser challenge, static assets and unrelated rules remain
   intact.

## Legacy Parity

### Dashboard

1. Populate `beszel-password`, `home-assistant-key`, `immich-key`,
   `linkwarden-key`, `miniflux-key`, `truenas-key` and `unifi-key` in the
   existing display-named `Homepage` item in the `mbk` cluster vault. The
   Beszel username defaults to `admin@excloo.com`. Force an External Secret
   refresh and restart Homepage once after initial population; values remain
   outside Git and missing values hide only their widget.
2. Add Tailscale device widgets only after recording the retained devices'
   stable device IDs. Expose the Traefik widget only through a cluster-internal
   API Service with a NetworkPolicy limited to Homepage; do not expose the
   unauthenticated dashboard API through a shared route.
3. Validate the Services and Servers tabs at desktop and mobile widths. Confirm
   widget-bearing cards sort first, other local and explicit `syd` cards merge
   alphabetically and no remote card duplicates local discovery.

### Identity

1. Test both the existing Beszel password login and Pocket ID against
   `beszel.excloo.com`. Confirm its persisted PocketBase provider uses the same
   issuer, client and callback; keep `DISABLE_PASSWORD_AUTH` false.
2. Complete an interactive Pocket ID login against `grafana.excloo.com` after
   its retained client is reconciled. Keep `grafana.syd.excloo.dev` local-only
   while Pocket ID automation remains available only on `mbk`.
3. Audit every remaining OIDC-enabled workload for a usable local recovery
   account. Record product limitations explicitly rather than disabling OIDC;
   in particular, verify Shelfmark still exposes its local form while
   `AUTH_METHOD=oidc`.

## Stretch

### Dashboard

1. Restore the `mbk` and `syd` Cloudflare Tunnel widgets after Crossplane or
   another declarative Kubernetes source publishes both tunnel identifiers for
   Homepage. Keep only the shared `Account.Cloudflare Tunnel:Read` token in
   1Password; do not give Homepage access to either tunnel runtime token.

### External Monitoring

1. Remove `homelab-fly`'s stale dependency on the retained `CONFIG` repository
   variable. Keep Fly machine, certificate, alerting and UI configuration in
   `homelab-fly`; the current `homelab` root no longer owns or publishes a
   service catalogue.
2. During the ephemeral `homelab-fly` render, check out public Kubelab `main`
   and derive HTTP probes from both standard `HTTPRoute` resources and the
   routes declared in upstream app-template `HelmRelease` values. Select only
   routes carrying `gethomepage.dev/enabled: "true"`; use the checked Homepage
   name, group, href and site-monitor annotations rather than adding another
   service schema. Keep the normaliser narrow to those two current Kubernetes
   representations and fail if an enabled route uses an unsupported shape.
   Keep route-specific overrides, provider and DNS probes, and retained-
   appliance probes as direct Gatus YAML fragments in `homelab-fly`; Gatus
   natively merges its configuration directory.
3. Use `<cluster> / <Homepage group>` for generated groups and the Homepage
   name without an old target suffix. The current baseline is 29 enabled and
   accepted routes: 24 from `mbk` and five from `syd`. Include Cloudflare and
   Control D DNS checks, provider checks, Gatus itself and retained-appliance
   probes as direct fragments. Remove all 33 retained `excloo.dev` catalogue
   probes, the old `au-truenas` and `au-hsp` suffixes, stopped Docker targets
   and deleted service URLs. Fail rendering on duplicate endpoint keys, invalid
   URLs or an empty generated route inventory.
4. Preserve the independent Fly failure domain, sending-only mail credential,
   Tailscale reachability, alert thresholds and Redlib `X-Gatus-Token` bypass.
   Prove one failing and one recovered alert without exposing the token.

### Observability

1. Extend VictoriaMetrics and VictoriaLogs retention from seven to 90 days only
   after measuring current ingestion, local-path capacity and compaction load.
   Keep the data replaceable and set a documented capacity ceiling.
2. Decide whether to restore the TrueNAS Graphite listener on TCP `2003`, the
   previous infrastructure dashboard, explicit Cloudflared and Traefik metrics,
   and actionable dashboards or alert rules. Keep appliance ingestion behind
   reviewed Tailscale and NetworkPolicy boundaries.

### Retained Systems

1. Re-establish declarative Beszel agent coverage for HAOS, Hotdog, Mandu,
   TrueNAS and UniFi where the platform supports an agent. Keep the Kubernetes
   DaemonSets for cluster-node summaries and use Kubernetes-native metrics for
   workload diagnosis.
2. Add the retained systems to Homepage only after their live management URL or
   Beszel system identifier is confirmed. Record unsupported systems instead of
   creating dead cards.

## Staged Integrations

### RoMM Library Workflows

Either activate or remove the suspended `romm-workflows` Job template. Before
enabling any destructive mode, add the reviewed non-DAT manifests and request
approval for the disposable NFS-copy validation. Do not add a migration test
harness.

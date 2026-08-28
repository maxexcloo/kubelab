# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## Reconciliation Blockers

1. Remove one of the two display-named `LaraPaper` items from the `mbk` cluster
   vault so External Secrets can select exactly one item. Force a refresh if
   required, then reconcile `apps`, `pocket-id-automation` and the cluster root
   at the current `main` revision. The retained application Secret remains
   present while reconciliation is blocked.
2. Apply the current `homelab` `main` branch with its normal credentials to
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

1. Populate the existing display-named `Homepage` item in the `mbk` cluster
   vault with only the still-live widget credentials. Restore the selected
   Beszel, Home Assistant, Immich, Linkwarden, Miniflux, Tailscale, Traefik,
   TrueNAS and UniFi widgets through `HOMEPAGE_VAR_*` substitutions; never put
   their values in Git.
2. Validate the Services and Servers tabs at desktop and mobile widths. Keep
   widget-bearing cards first and otherwise preserve the legacy alphabetical
   order; check that the explicit `syd` cards do not duplicate local discovery.

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

1. Recover the accepted Gatus configuration and operational data from the
   archived `homelab` model and the current `homelab-fly` `CONFIG` repository
   variable. Give the rendered endpoint inventory one declarative owner without
   moving the Fly runtime into Kubernetes.
2. Rebuild the inventory from accepted routes and retained appliances in both
   clusters. Include Cloudflare and Control D DNS checks, provider checks,
   internal and external host checks and the current public and private URLs;
   remove stopped TrueNAS and Docker targets.
3. Preserve the independent Fly failure domain, sending-only mail credential,
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

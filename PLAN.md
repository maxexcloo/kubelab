# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## External Automation

1. Review and apply the corresponding `homelab` plan to create
   the unqualified, `Homelab`-tagged `Backblaze B2`, `Cloudflare WAF`,
   `Control D` and `Resend` items in every corresponding cluster vault. Require
   the plan to preserve existing item and credential identities; do not accept a
   delete, replacement or token rotation while moving retained items from the
   `Homelab` vault. Confirm each B2 application key has `listBuckets`, `listKeys`,
   `readBucketEncryption`, `writeBucketEncryption`, `writeBuckets` and
   `writeKeys`, but no object-data, key-deletion or bucket-deletion capability.
   Treat `writeKeys` as full-account-equivalent control-plane access. Confirm
   each Cloudflare token has only Zone Read and Zone WAF Edit for `excloo.com`.
2. Populate `Control D` in the `mbk` cluster vault with the retained API token
   for profile `653224sydwhf`. Restore the retained Gatus bypass value as the
   concealed `monitoring-token` field on `Redlib` in the `syd` cluster vault.
   Preserve existing Resend values. Do not rotate any retained value until the
   existing Control D rules, mail delivery and Gatus access are proven.
3. Bootstrap only the 1Password Connect credentials and token for each cluster,
   then require the `Backblaze B2`, `Cloudflare WAF`, `Control D` and `Resend`
   ExternalSecrets to become Ready in `crossplane-system`. Verify provider
   credentials are non-empty before enabling a consumer; do not create any
   provider Secret manually.
4. Export the retained Cloudflare records and Control D rules for `budget`,
   `aiometadata`, `aiostreams`, `beszel`, `bichon`, `bifrost`, `chat`,
   `cliproxy`, `comfy-control`, `grafana`, `papra` and `reader`. Confirm each
   Cloudflare record is DNS-only and each Control D rule resolves to the current
   `private.mbk.excloo.dev` A and AAAA targets.
5. Resume `clusters/mbk/private-dns-automation.yaml`. Require both DNS target
   discovery Requests and every `PrivateDNSRecord` to become Ready, then verify
   Cloudflare and Control D answers independently before removing any legacy
   owner. Keep the inventory suspended if an existing record differs.
6. Review the existing Beszel B2 bucket and key settings, resume
   `clusters/mbk/b2-automation.yaml`, and require all three provider Requests to
   become Ready. Confirm the `B2ObjectStorage` claim reads the retained bucket
   name from `beszel-object-storage`, adopts exactly one `beszel` key with the
   fixed bucket-scoped capability profile and pushes only the access-key fields
   back to the `Beszel` item. The existing application key must remain unrotated;
   suspend the inventory if the bucket, key name, scope or capabilities differ.
7. Export the existing Cloudflare custom WAF phase, review the generated Redlib
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
2. Test both the Grafana administrator login and Pocket ID against
   `grafana.excloo.com`. Keep `grafana.syd.excloo.dev` local-only while Pocket ID
   automation remains available only on `mbk`.
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

### Home Assistant Webhook

Either activate or remove the suspended `home-assistant-webhook` inventory. To
activate it, confirm the HAOS address and certificate, verify that only
`/api/webhook` is exposed, resume the inventory and require the route and
`BackendTLSPolicy` to report Ready.

### RoMM Library Workflows

Either activate or remove the suspended `romm-workflows` Job template. Before
enabling any destructive mode, add the reviewed non-DAT manifests and request
approval for the disposable NFS-copy validation. Do not add a migration test
harness.

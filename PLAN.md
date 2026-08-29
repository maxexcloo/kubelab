# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## External Monitoring

1. Remove `homelab-fly`'s stale dependency on the retained `CONFIG` repository
   variable. Keep Fly machine, certificate, alerting and UI configuration in
   `homelab-fly`; the current `homelab` root no longer owns or publishes a
   service catalogue.
2. During the ephemeral `homelab-fly` render, check out public Kubelab `main`
   and derive HTTP probes from both standard `HTTPRoute` resources and the
   routes declared in upstream app-template `HelmRelease` values. Select only
   routes carrying `gethomepage.dev/enabled: "true"`; use the checked Homepage
   name, group, href and site-monitor annotations. Add the standard static
   Homepage `services.yaml` entries carrying `siteMonitor` so retained systems
   such as Home Assistant, TrueNAS and UniFi use the same source as the
   dashboards. Read the Git-owned configuration rather than querying a running
   Homepage instance. Do not add another service schema or publish the inventory
   through a GitHub variable. Keep the normaliser narrow to these three current
   representations and fail if an enabled entry uses an unsupported shape. Keep
   route-specific overrides and provider and DNS probes as direct Gatus YAML
   fragments in `homelab-fly`; Gatus natively merges its configuration directory.
3. Use `<cluster> / <Homepage group>` for generated groups and the Homepage
   name without an old target suffix. The current baseline is 30 enabled and
   accepted routes: 24 from `mbk` and six from `syd`. The 11 static Homepage
   entries do not overlap those routes, producing 41 unique service probes.
   Include Cloudflare and Control D DNS checks and provider checks as direct
   fragments. Remove all 33 retained `excloo.dev` catalogue probes, the old
   `au-truenas` and `au-hsp` suffixes, stopped Docker targets and deleted service
   URLs. Fail rendering on conflicting duplicates, invalid URLs or an empty
   generated route inventory.
4. Preserve the independent Fly failure domain, sending-only mail credential,
   Tailscale reachability, alert thresholds and Redlib `X-Gatus-Token` bypass.
   Prove one failing and one recovered alert without exposing the token.

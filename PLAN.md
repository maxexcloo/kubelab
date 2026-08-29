# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## External Automation

1. Decide whether to provision new Beszel B2 object storage or remove the
   suspended integration. A read-only review on 29 August 2026 confirmed that
   the configured account has no Beszel bucket or application key and the
   display-named `Beszel` item has no object-storage fields, so there is no
   retained resource to adopt. Keep `clusters/mbk/b2-automation.yaml` suspended
   unless a reviewed globally unique bucket name and new bucket-scoped
   application key creation are explicitly approved.

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
   dashboard. Do not add another service schema or publish the inventory through
   a GitHub variable. Keep the normaliser narrow to these three current
   representations and fail if an enabled entry uses an unsupported shape.
   Keep route-specific overrides and provider and DNS probes as direct Gatus
   YAML fragments in `homelab-fly`; Gatus natively merges its configuration
   directory.
3. Use `<cluster> / <Homepage group>` for generated groups and the Homepage
   name without an old target suffix. The current baseline is 29 enabled and
   accepted routes: 24 from `mbk` and five from `syd`. The 16 static Homepage
   entries overlap five of those routes, producing 40 unique service probes.
   Include Cloudflare and Control D DNS checks and provider checks as direct
   fragments. Remove all 33 retained `excloo.dev` catalogue probes, the old
   `au-truenas` and `au-hsp` suffixes, stopped Docker targets and deleted service
   URLs. Fail rendering on conflicting duplicates, invalid URLs or an empty
   generated route inventory.
4. Preserve the independent Fly failure domain, sending-only mail credential,
   Tailscale reachability, alert thresholds and Redlib `X-Gatus-Token` bypass.
   Prove one failing and one recovered alert without exposing the token.

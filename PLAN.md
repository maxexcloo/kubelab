# Plan

This file contains only unfinished work. Current architecture and operations
are documented in `README.md`; completed migration history remains in Git.

## External Automation

1. Create `B2 Automation: mbk` in the `Homelab` vault with a B2 application key
   limited to `listBuckets`, `listKeys`, `readBucketEncryption`,
   `writeBucketEncryption` and `writeBuckets`. Do not grant bucket or key delete
   authority or key creation authority.
2. Create `Cloudflare App Policy: mbk` with Zone Read and Zone WAF Edit limited
   to `excloo.com`. Add the retained Gatus bypass value as a concealed
   `monitoring-token` field.
3. Run `mise run bootstrap-automation-secrets mbk`.
4. Review the existing Beszel B2 bucket and key settings, resume
   `clusters/mbk/b2-automation.yaml`, and require all three provider Requests to
   become Ready. The existing application key remains observation-only.
5. Export the existing Cloudflare custom WAF phase, review the generated Redlib
   rule, resume `clusters/mbk/cloudflare-automation.yaml`, and verify that the
   Gatus bypass, browser challenge, static assets and unrelated rules remain
   intact.

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

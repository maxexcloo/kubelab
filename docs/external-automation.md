# External Automation

B2 and Cloudflare application policy are implemented on `mbk`, where Crossplane
runs, but their Flux inventories are suspended. This prevents an unavailable
bootstrap credential or an unreviewed WAF update from affecting reconciled
workloads.

## Bootstrap Credentials

Create these Login items in the `Homelab` vault before running the bootstrap
task:

| Item                         | Username              | Password             | Minimum authority                                                                              |
| ---------------------------- | --------------------- | -------------------- | ---------------------------------------------------------------------------------------------- |
| `B2 Automation: mbk`         | B2 application key ID | B2 application key   | `listBuckets`, `listKeys`, `readBucketEncryption`, `writeBucketEncryption`, and `writeBuckets` |
| `Cloudflare App Policy: mbk` | Operator label        | Cloudflare API token | Zone Read and Zone WAF Edit, scoped only to `excloo.com`                                       |

Do not grant the B2 controller `deleteBuckets`, `deleteKeys`, or `writeKeys`.
The legacy Beszel key cannot be recovered from the B2 API and remains adopted
from the `Beszel` item instead of being rotated automatically.

Once the items exist, seed only the Kubernetes bootstrap Secrets:

```shell
mise run bootstrap-automation-secrets mbk
```

The task also copies the existing Redlib monitoring token from the `Cluster:
syd` vault into the `mbk` controller Secret. It does not print credential
values or write them to Git.

## B2 Activation

1. Confirm `Beszel` contains the migrated `object-storage-*` fields and that its
   configured S3 backup can list and restore a disposable backup.
2. Capture the current bucket privacy, encryption, lifecycle rule, key ID,
   bucket scope, and key capabilities in the change record.
3. Remove `spec.suspend: true` from `clusters/mbk/b2-automation.yaml` in a
   reviewed change.
4. Require all three provider-http Requests in the `beszel` namespace to become
   Ready. The key Request is observation-only; any mismatch requires a reviewed
   manual rotation and a Beszel restore test.
5. Leave the old fields and previous deployment recoverable for the seven-day
   rollback window.

Deleting the Flux or Crossplane resources does not delete the B2 bucket or key.

## Cloudflare Activation

1. Export the current `http_request_firewall_custom` phase response to secure
   change evidence and count every existing rule.
2. Confirm the Redlib monitoring token matches the retained Gatus endpoint.
3. Review the generated rule expression in
   `platform/automation/cloudflare/redlib-waf-policy.yaml` against the legacy
   rule.
4. Remove `spec.suspend: true` from
   `clusters/mbk/cloudflare-automation.yaml` in a reviewed change.
5. Confirm zone discovery returns exactly `excloo.com`. The first WAF update
   adds the stable `kubelab-redlib-js-challenge` reference, preserves unrelated
   rules in their existing order, and retains all legacy static-asset bypasses.
6. Verify ordinary browser traffic receives the JS challenge, requests with the
   Gatus header bypass it, static assets load, and the rule count is unchanged.

If verification fails, suspend the Flux inventory and restore the captured
phase response through the Cloudflare API. Deleting the composite has no delete
authority over the external ruleset.

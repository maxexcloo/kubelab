# State Bootstrap

This stack must import the existing `homelab-opentofu` bucket; it must never
try to create a second bucket or replace the existing one.

1. Confirm the bucket's project and immutable location with `gcloud storage
buckets describe gs://homelab-opentofu`.
2. Initialise this directory and supply the existing project and location.
3. Import with `tofu import google_storage_bucket.state homelab-opentofu`.
4. Save and review a plan. It must not replace the bucket. Review any access,
   versioning, or retention change separately before applying.

The retention policy is deliberately not locked. Locking it is irreversible
and needs a separate decision after recovery has been tested.

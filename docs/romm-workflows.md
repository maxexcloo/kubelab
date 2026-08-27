# RoMM Workflows

RoMM library maintenance runs as manually created Kubernetes Jobs on `mbk`.
The suspended `romm-workflows` CronJob is a Job template only; it never runs on
a schedule. It replaces the `homelab-workflows` GitHub Actions runner without
giving CI access to the games library.

## Safety Contract

- Every mode takes one non-blocking NFS advisory lock. A second Job fails before
  it reads or writes library content, and the kernel releases the lock when a
  Pod exits.
- IGIR `5.0.2` and Fresh1G1R revision
  `5b8f9e0ebb0c34573805c337a375bbe3ee8fbec1` are pinned with SHA-256 digests.
  Downloads use a retained cache under `/games/workflow/tools` and are verified
  before use.
- `audit` and `reconcile` fail closed while `non_dat_manifests` is empty. Each
  configured manifest must itself have a reviewed digest and may reference only
  files beneath a configured source root.
- `reconcile` also requires the exact application-consistent restore evidence in
  `/games/workflow/reports/application-consistent-restore.confirmed` and an empty
  `/games/library.next`. It never replaces the live library.
- `ingest` validates a complete batch into a run-specific directory before any
  publication. It preflights every collision, journals each per-file atomic
  rename, verifies each destination hash, and moves the inbox batch to
  `processed` only after the whole publication verifies.
- `export` fails closed until RoMM 5.2.0 ES-DE export and collection filtering
  have been compatibility-tested.

The configuration and implementation live in
`apps/base/romm/workflows-config-map.yaml`. This is a narrow RoMM-specific
contract, not a general workload or workflow schema.

## Running a Job

Use a unique lower-case Job name. Inventory is the default mode:

```bash
kubectl --context mbk --namespace romm create job \
  --from=cronjob/romm-workflows romm-inventory-20260827
```

For another mode, render the Job locally, change its environment before a Pod
exists, then apply it:

```bash
kubectl --context mbk --namespace romm create job \
  --from=cronjob/romm-workflows romm-audit-20260827 \
  --dry-run=client --output=yaml |
  kubectl set env --local --filename=- MODE=audit --output=yaml |
  kubectl --context mbk --namespace romm apply --filename=-
```

Ingest requires a reviewed batch name and the exact confirmation:

```bash
kubectl --context mbk --namespace romm create job \
  --from=cronjob/romm-workflows romm-ingest-example-20260827 \
  --dry-run=client --output=yaml |
  kubectl set env --local --filename=- \
    MODE=ingest \
    BATCH=example \
    CONFIRMATION='PUBLISH VERIFIED ROMS' \
    --output=yaml |
  kubectl --context mbk --namespace romm apply --filename=-
```

Reconcile uses the same confirmation and additionally enforces its restore and
empty-staging gates:

```bash
kubectl --context mbk --namespace romm create job \
  --from=cronjob/romm-workflows romm-reconcile-20260827 \
  --dry-run=client --output=yaml |
  kubectl set env --local --filename=- \
    MODE=reconcile \
    CONFIRMATION='PUBLISH VERIFIED ROMS' \
    --output=yaml |
  kubectl --context mbk --namespace romm apply --filename=-
```

Follow a run with:

```bash
kubectl --context mbk --namespace romm logs \
  --follow job/romm-inventory-20260827
```

## Interrupted Ingest

Do not delete a report, journal, validation directory, or processed batch after
an interruption. Start a new ingest Job with the same batch name. Publication
accepts already-present destinations only when their hashes match the newly
validated files, so it resumes verified work and still rejects a conflicting
destination before moving another file.

If the inbox has already moved to `processed`, the rerun reports that the batch
is complete. Investigate any preserved `*.invalid-*` or run-specific validation
directory before removing it.

## Cutover Gate

The RoMM Helm release remains suspended and its namespace is not authorised for
the public Gateway. Before unsuspending it:

1. Restore the final PostgreSQL export into `romm-database` and copy the retained
   configuration into `/mnt/truenas-nvme/romm/config`.
2. Confirm the NFS library, assets, resources, Pocket ID login, metadata
   providers, and `/api/heartbeat` through the cluster-local service. Create one
   manual Job from the suspended `romm-backup` schedule and validate its dump
   before enabling the schedule through Git.
3. Run the workflow modes against a disposable copy and compare the resulting
   file manifest with the source evidence.
4. Add the public namespace/route labels and ExternalDNS annotation in the
   reviewed cutover change, then begin the seven-day rollback window.

# Storage

## TrueNAS 26 CSI Evaluation

Do not deploy `democratic-csi` against TrueNAS 26.

TrueNAS 26 removed the REST API and supports the versioned JSON-RPC 2.0
WebSocket API. `democratic-csi` still documents TrueNAS operations through the
REST `/api/v2.0` interface, describes its API-only SCALE drivers as
experimental, and otherwise requires privileged SSH access to the storage
appliance. This does not meet the repository's rebuild, security, or upgrade
health requirements.

The official TrueNAS CSI driver `v1.1.2` uses the supported WebSocket API. Its
documented requirements are TrueNAS 25.10 or later and Kubernetes 1.26 or
later, so TrueNAS 26 and the `mbk` cluster meet its version gates. It is the
preferred dynamic-storage trial candidate even if a future suitable release is
marked pre-release.

Keep NFS as the production default until the trial passes. `homelab` owns the
cluster-scoped `truenas-nvme/clusters/mbk` dataset, its NFS export, snapshots,
and replication. The upstream NFS subdirectory provisioner in `kubelab` creates
one retained directory per claim beneath that export through the `truenas-nfs`
storage class. Keep node-local `local-path` volumes limited to replaceable
state.

Existing standalone datasets remain explicit exceptions. Export each approved
dataset in `homelab`, define a retained static `PersistentVolume` in `kubelab`,
and bind it to the workload through a namespaced claim. Do not expose a whole
pool.

### Trial Acceptance

Use NFS first because it requires no additional Talos node extension. Pin the
driver and every sidecar image, materialise a least-privilege TrueNAS API key
through External Secrets, and create a non-default trial storage class.

The trial must prove:

1. Dynamic provisioning and mounting from a non-root pod.
2. Online expansion without data loss.
3. Snapshot creation and restoration into a second claim.
4. Retained-volume recovery after deleting and recreating the claim and driver.
5. Workload and volume recovery after an `mbk` node restart.
6. Healthy reconciliation across a TrueNAS patch upgrade.

Do not trial iSCSI until the required Talos `iscsi-tools` extension is part of a
reviewed substrate change. Promote a CSI storage class to production only after
recording the test results here.

### References

- [TrueNAS 26 feature deprecations](https://www.truenas.com/docs/scale/26/gettingstarted/deprecations/)
- [TrueNAS CSI driver](https://github.com/truenas/truenas-csi)
- [`democratic-csi` TrueNAS server preparation](https://github.com/democratic-csi/democratic-csi#freenas-freenas-nfs-freenas-iscsi-freenas-smb-freenas-nvmeof-freenas-api-nfs-freenas-api-iscsi-freenas-api-smb-freenas-api-nvmeof)

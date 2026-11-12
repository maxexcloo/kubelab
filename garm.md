# GARM

GARM runs disposable GitHub Actions VMs on Mercury's Incus. The
[application manifests](apps/base/garm) own the deployment, provider configuration,
routes and secrets. Homelab owns
[Mercury's Incus provisioning](https://github.com/maxexcloo/homelab#mercury-incus).

## Enrolment

[The enrolment job](apps/base/garm/enrol.py) discovers active repositories owned
by `maxexcloo`, including owned forks, through an **All Repositories** GitHub App
installation. It reconciles one native repository scale set per eligible repo;
other credentials and differently named scale sets remain separately managed.
Discovery must complete before changes start. Ineligible managed scale sets are
disabled, never deleted; an interrupted run resumes on its next scheduled run.
Rotate existing App credentials through GARM's supported API when its key changes.

Select `runs-on: mercury-incus` to opt a workflow in. Scale sets scale to zero
and receive durable queued demand from GitHub, including while GARM is offline.
The Incus project's capacity is the global bound; each scale set's maximum only
bounds that repository. Quota-rejected creates are cleaned up and retried while
demand remains. Automatic retries do not guarantee global FIFO order or a bounded
wait.

## Connectivity

[The Incus provider configuration](apps/base/garm/incus.toml) selects the remote
project/profile and authenticates with a project-restricted client certificate.
The existing node network supplies tailnet connectivity; no application Tailscale
sidecar is needed. Check the scheduled node's actual egress identity after a
placement change or restore: Mercury must allow the Talos node's Tailscale IP,
not a TrueNAS host's separate identity or the pod address. Homelab owns the node
path in [talos.tf](https://github.com/maxexcloo/homelab/blob/main/talos.tf) and
[truenas.tf](https://github.com/maxexcloo/homelab/blob/main/truenas.tf);
[Cilium](platform/networking/cilium/helm-release.yaml) supplies host routing and
masquerading.

[The routes](apps/base/garm/routes.yaml) keep administration private and expose
only instance-authenticated callbacks and metadata publicly. Cloudflare must
allow those machine requests without browser challenges or Access authentication.
Runner egress isolation is enforced by Mercury's firewall, independently of the
controller's Kubernetes NetworkPolicy. Guests receive no Incus credentials or
tailnet identity.

## Activation & Recovery

Activation and workflow changes require separate review:

1. Complete Homelab's host activation checks. Confirm the configured capacity,
   storage, bridge, firewall and VM hardware support. Set the controller's actual
   egress IP in Mercury's allow-list and verify pod-to-Incus routing and TLS.
2. Create a GitHub App installed on all `maxexcloo` repositories, with repository
   **Administration: Read & write** and **Metadata: Read-only** permissions.
   Repository scale sets need no organisation permissions or webhooks.
3. Populate the external fields declared in
   [external-secrets.yaml](apps/base/garm/external-secrets.yaml) in the **GARM**
   1Password item. The App key must be RSA PKCS#1 PEM; the database passphrase must
   be a strong random string of exactly 32 characters. Preserve it and the JWT
   secret for recovery. Supply the administrator credentials and real Incus
   client certificate/key and pinned server certificate. Install only that
   client's public certificate as project-restricted trust on Mercury.
4. Review the routes, then deploy. Verify public DNS/TLS and machine paths from
   outside the private network; ensure public UI and admin/login paths remain
   unavailable. Initialise GARM through the private UI using the stored
   credentials. Enrolment fails safely until initialisation and secrets are ready.
   Check the bundled provider against its deployed configuration when upgrading.
5. Verify enrolment and the scale-set listener on one test repository. With live
   test approval, run a disposable VM job; check resources, denied host/LAN/tailnet/
   metadata access, allowed public egress, deregistration and VM deletion.
6. Queue jobs in two repositories, keeping the first running through repeated
   capacity rejections. Verify the host's configured limit holds and the waiting
   job recovers automatically after capacity is released. Restart GARM with jobs
   queued and verify automatic recovery. Stop rollout if manual retries are needed.

[The backup job](apps/base/garm/backup.yaml) stops GARM while copying SQLite state.
Restore the database and original passphrase/JWT secret before starting it;
retain the controller ID, repository entities and scale-set IDs so existing
GitHub queues stay associated with the restored controller. Reconcile existing
Incus instances before accepting more jobs, and test restores separately.

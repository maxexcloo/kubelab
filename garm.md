# GARM

GARM manages disposable Ubuntu VMs on Mercury's Incus for repository-scoped
GitHub Actions runners. The application uses the existing app-template chart;
upstream documents an operator for Kubernetes, rather than a standalone chart.
The GARM image includes the external Incus provider. Renovate follows the exact
image tags through its native Kubernetes and Flux managers.

## Enrolment

The app-owned CronJob discovers repositories every ten minutes using a GitHub
App installation token. Install the App on **All Repositories** for the personal
`maxexcloo` account, so new repositories are discoverable automatically. Active
means owned by that account, not archived and not disabled; owned forks are
included. Organisation and foreign repositories are excluded.

Discovery completes every GitHub response page before GARM changes start. An API
error, incomplete inventory, suspended installation or selected-repository
installation fails the run. The next scheduled run retries. No repository or
scale set is deleted. Scale sets that this script owns are disabled when a
complete inventory excludes their repository, then re-enabled if it becomes
eligible again. Other credentials and differently named scale sets remain
separately managed; conflicting repository credentials or a matching scale set
using another provider fail rather than silently adopting it.

The script logs in to GARM for a fresh token, sets the controller's public URLs,
creates the GitHub App credential once, and creates one repository scale set
named `mercury-incus` per eligible repository. GARM's repository API still
requires an independent random `webhook_secret` when creating the repository
entity; no webhook is installed or exposed. An interrupted run resumes from the
resources already created. Existing GitHub App credentials are not overwritten:
rotate the GARM credential through its supported API when the external App key
changes.

Scale sets use GitHub's native long-poll message queue. Jobs queued while GARM
is offline stay queued until it reconnects. GARM persists each scale set's
requested runner count and reconciles towards that demand. The enrolment job
does not schedule jobs or manage individual VMs.

Scale sets scale to zero. No workflow is switched by this change. Select
`runs-on: mercury-incus` only in an explicitly approved rollout test. That is
the scale set's name; no generic labels such as `self-hosted` are added, so it
cannot claim existing jobs that have not opted in.

## Capacity & Isolation

The host contract is implemented in
[Homelab PR #333](https://github.com/maxexcloo/homelab/pull/333), with the Incus
server image supplied by
[Bluemax PR #41](https://github.com/maxexcloo/bluemax/pull/41).
The provider connects by authenticated TLS over the tailnet, selects the `garm`
project, and uses its `garm-vm` profile without adding the default profile.
The profile owns CPU, memory, root disk and network configuration.

The **global bound is Incus project capacity**, independently of how many GARM
repository scale sets exist: `limits.instances=1`, `limits.virtual-machines=1` and
`limits.containers=0`. The single VM has 4 CPU, 6 GiB RAM and a 64 GiB root disk
on native local storage. A stopped VM also consumes that capacity. Each scale set's
`max_runners=1` only bounds that repository; it does not enforce the host bound.

The Incus provider forwards quota rejection as a creation failure. GARM's
scale-set provider worker marks the failed instance for deletion. Once that
instance is removed, the autoscaling worker requests a replacement while the
persisted runner demand remains. Unlike webhook pools, this path has no
five-attempt ceiling, so waiting repositories keep retrying without a manual
job restart.
The provider treats deletion of an absent instance as success.

This gives each repository durable job delivery and automatic recovery from
capacity rejection. The Incus quota is a hard host bound, not a global FIFO
queue or a fairness guarantee. Competing repositories can still delay one
another; no bounded wait or strict execution order is promised. Verify
two-repository contention and controller-restart recovery during activation.

Homelab owns the isolated NAT bridge and firewall. Runner traffic cannot reach
the host, private networks, LAN, tailnet, link-local or cloud metadata addresses;
DHCP and public DNS/package/GitHub access are handled by that host contract.
No runner receives Incus credentials or a tailnet identity. This PR's NetworkPolicy
allows the ingress gateway and enrolment job to reach GARM; VM egress isolation
is enforced on Mercury, not by Kubernetes NetworkPolicy.

Controller connectivity uses the cluster's existing node network, with no
application Tailscale sidecar: the GARM pod leaves through Cilium's legacy host
routing and IPv4 iptables masquerading, then the node's kernel `tailscale0`
interface reaches Mercury. Cilium's checked-in configuration keeps legacy host
routing enabled and leaves the chart's IPv4 masquerading defaults in place;
there is no GARM egress-deny policy. The upstream
[masquerading contract](https://docs.cilium.io/en/stable/network/concepts/masquerading/#iptables-based)
covers traffic leaving non-Cilium interfaces such as `tailscale0`.

Homelab owns that node path in
[talos.tf](https://github.com/maxexcloo/homelab/blob/main/talos.tf) and
[truenas.tf](https://github.com/maxexcloo/homelab/blob/main/truenas.tf): direct
nodes use the kernel Tailscale extension, while Saturn's Talos container shares
its network namespace with a kernel-mode Tailscale sidecar (`TS_USERSPACE=false`).
The Talos routing rule at priority 5200 sends tailnet destinations through table
52 before Cilium packet marks can bypass it. Homelab's
[dns.tf](https://github.com/maxexcloo/homelab/blob/main/dns.tf) publishes Mercury's
infrastructure hostname to its Tailscale addresses.

With the current
[cluster placement](https://github.com/maxexcloo/homelab/blob/main/data/clusters.yaml),
Saturn is the untainted internal node eligible for this controller; Venus is
reserved for GPU workloads and Neptune is external. Mercury's listener allow-list
must therefore use the **Talos container's** configured Tailscale IPv4, rather
than the TrueNAS host's separate identity or the pod address. Recheck the scheduled
node after a restore or placement change. This establishes the configured path;
pod-to-Incus TLS connectivity still needs a live activation check.

GARM's public route exposes only `/api/v1/callbacks` and `/api/v1/metadata`
through the Cloudflare tunnel. GARM authenticates runner requests with instance
JWTs. Webhook management remains disabled and no webhook route is published.
The UI, first-run, login and administration API remain on the private route.
The enrolment job derives the public callback/metadata URLs from the public
route, so bootstrap needs no private IP/port firewall exception. Cloudflare must
allow these machine clients without browser challenges or Access authentication.

## Activation & Recovery

This PR does not merge or deploy any component, create a GitHub App, install
Incus trust, populate secrets, change routes live, or exercise a live VM job.
Activation requires separate approval and the following work:

1. Review and deploy the dependent host/image changes. Confirm the project limits,
   isolated bridge, firewall, VM hardware support and profile before enabling
   GARM. Record the actual controller egress Tailscale IPv4 in Homelab's listener
   allow-list; verify cluster DNS and routing reach the private Incus endpoint.
2. Create a GitHub App installed on all `maxexcloo` repositories. Grant repository
   **Administration: Read & write** and **Metadata: Read-only**. Organisation
   permissions, Webhooks permissions and webhook subscriptions are unnecessary:
   repository scale sets obtain their demand through GitHub's message queue.
3. Populate the external fields declared in `external-secrets.yaml` in the
   **GARM** 1Password item. The App key must be RSA PKCS#1 PEM, as required by the
   released GARM API. The database passphrase must be a strong random string of
   exactly 32 characters; the JWT secret must be strong random material. Preserve
   both for recovery. Set the intended administrator username/password and supply
   the real Incus client certificate/key and verified server certificate. Install
   only that genuine client's public certificate as project-restricted trust for
   `garm` on Mercury; never grant unrestricted Incus trust.
4. Approve the new routes, then deploy this application. Verify public DNS/TLS and
   the machine paths from outside the private network; confirm the public UI and
   admin/login paths remain unavailable. Initialise GARM through the private UI
   using the stored administrator credentials. The CronJob fails safely until
   initialisation and all credentials are ready. Check the bundled provider
   version against the reviewed provider release when activating or upgrading.
5. Verify enrolment and the native scale-set listener on one test repository. With
   explicit live-test approval, run one disposable VM job, verify CPU/RAM and
   denied host/LAN/tailnet/metadata access, verify allowed GitHub/package egress,
   and confirm runner deregistration and VM deletion. Queue jobs in two different
   repositories simultaneously and keep the first running through repeated
   capacity rejections: prove at most one VM exists and that the other job eventually
   recovers after release of capacity. Restart GARM while jobs remain queued
   and verify they run automatically after reconnection. Pause rollout if
   recovery needs manual intervention. No existing workflow fleet changes are
   part of activation here.

SQLite state uses one replica, `Recreate` and a retained local-path claim. The
shared file-backup job stops the controller while copying state to Restic.
During recovery, restore the database and original passphrase/JWT secret before
starting GARM; retain the controller ID, repository entities and scale-set IDs
so GitHub's existing queues remain associated with the restored controller.
Reconcile existing Incus instances before accepting more jobs. Test restores
separately.

## Upstream Contracts

The implementation was checked against released source, rather than unreleased
`main` documentation:

- [GARM v0.2.1 credentials](https://github.com/cloudbase/garm/blob/v0.2.1/doc/credentials.md)
  and [request types](https://github.com/cloudbase/garm/blob/v0.2.1/params/requests.go)
  define App authentication, base64-encoded key bytes, login, controller updates
  and repository/scale-set requests.
- [Repository API](https://github.com/cloudbase/garm/blob/v0.2.1/apiserver/controllers/repositories.go)
  and [routers](https://github.com/cloudbase/garm/blob/v0.2.1/apiserver/routers/routers.go)
  define repository scale-set creation and instance-authenticated public paths.
- [Scale-set documentation](https://github.com/cloudbase/garm/blob/v0.2.1/doc/scale-sets.md),
  [listener](https://github.com/cloudbase/garm/blob/v0.2.1/workers/scaleset/scaleset_listener.go),
  [autoscaler](https://github.com/cloudbase/garm/blob/v0.2.1/workers/scaleset/scaleset.go)
  and [provider worker](https://github.com/cloudbase/garm/blob/v0.2.1/workers/provider/instance_manager.go)
  define durable demand, failed-instance deletion and replacement. Provider-wide
  capacity scheduling is an [upstream request](https://github.com/cloudbase/garm/issues/204).
- [Incus provider v0.1.5 configuration](https://github.com/cloudbase/garm-provider-incus/blob/v0.1.5/config/config.go)
  and [implementation](https://github.com/cloudbase/garm-provider-incus/blob/v0.1.5/provider/incus.go)
  define remote TLS, projects, profile flavours, VM mode and error propagation.
- GitHub documents [installation-token creation](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)
  and [paginated installation repositories](https://docs.github.com/en/rest/apps/installations#list-repositories-accessible-to-the-app-installation).

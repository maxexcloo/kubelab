# SignTools

The web service is configured to run in `syd` and dispatch signing jobs to the private
`maxexcloo/signtools-builder` GitHub repository. The proposed endpoint is
`https://signtools.excloo.com`, using the existing private gateway and private DNS.
Keep SideStore available until an app has been signed, installed and tested on the
target device.

## Builder

The [builder repository](https://github.com/maxexcloo/signtools-builder) owns its
workflows, scripts, tests and development tooling. Start signing requests through
SignTools so it queues a job before dispatching the workflow. Apple sessions are
stored as GitHub repository secrets; expired sessions require 2FA in SignTools.

The runner joins Tailscale as an ephemeral `tag:ephemeral` device using
workload identity federation. Homelab declares the federated identity restricted
to `maxexcloo/signtools-builder` on `main`, with the `auth_keys` write scope and
that tag. After applying its reviewed plan, use the
`github_identity` output to set repository secrets `TS_OAUTH_CLIENT_ID`
from `client_id` and `TS_AUDIENCE` from `audience`, without printing their values.
The action logs the device out after the job.
The workflow checks HTTPS connectivity before signing begins.

Tailnet policy is owned by `homelab/data/access.yaml` and `homelab/tailscale.tf`.
Ephemeral devices are excluded from the broad tagged-device grant and receive only TCP
port 443 access to the discovered `syd` gateway addresses. The gateway is shared by other
private applications, so this grants network access to its HTTPS listener, with
application authentication providing the remaining separation. Verify the policy
and private DNS resolution in the first workflow run.

Create a fine-grained GitHub token restricted to the builder repository with
Actions and Secrets read/write permissions. Set repository secret
`SESSION_STORAGE_TOKEN` from the same token through local credential tools; only
the session-saving step receives it. SignTools sets `SECRET_KEY` and
`SECRET_URL` itself at startup; do not copy them manually. Use a zero-spend Actions
budget with usage blocking if signing must stop when the included allowance runs
out. The account's other private workflows share that allowance.

## Credentials

The `SignTools` 1Password item supplies these fields:

| Field                          | Purpose                                                   |
| ------------------------------ | --------------------------------------------------------- |
| `apple-account-name`           | Paid Apple developer account email                        |
| `apple-account-password`       | Apple account password; signing may prompt for 2FA        |
| `certificate-base64`           | Base64-encoded exported `.p12`, including its private key |
| `certificate-password`         | Password protecting the `.p12`                            |
| `provider-github-access-token` | Builder repository token                                  |

Populate credentials through local credential tools without printing their values.
The signing profile is mounted read-only with a stable `developer` ID, so saved
apps retain their profile association across restarts. The application rewrites
its runtime configuration, including the GitHub token, in a
memory-backed `/tmp`; uploaded apps remain on the retained NFS claim. Restart the
workload after credential changes because SignTools reads them at startup.

## Access & Trial

The web UI has no login; devices that can reach the private gateway can use it.
Worker endpoints retain SignTools' generated bearer key, while app download and
installation links are accessible to devices that can reach the private gateway
and have their URLs.
The iPhone needs LAN or Tailscale connectivity while uploading and installing;
the GitHub runner uses Tailscale for its callbacks. Keep trusted HTTPS enabled
for iOS OTA installation. There is no public route or Cloudflare tunnel for this app.

After deployment, verify the UI opens without a login, uploads trigger the private
workflow, and an IPA with the required tweaks signs
and installs successfully. Test app extensions and retained data before replacing
an existing installation or removing SideStore.

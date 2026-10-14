# SignTools

The web service is configured to run in `mbk` and dispatch signing jobs to the private
`maxexcloo/signtools-builder` GitHub repository. The proposed endpoint is
`https://signtools.excloo.com`, using the existing private gateway and private DNS.
Keep SideStore available until an app has been signed, installed and tested on the
target device.

## Builder

Create the private repository with `main` as its default branch and copy
`builder/sign.yaml` to `.github/workflows/sign.yaml` and `builder/run_signer.py` to
`run_signer.py` at the repository root. Also copy `builder/check_connection.py` to
`check_connection.py` at the repository root. The wrapper masks downloaded passwords in
GitHub logs before upstream error reporting can include command arguments.
The workflow checks out a fixed upstream signing revision because SignTools-CI
does not publish release tags. The standard Intel macOS runner supports the
bundled tweak-injection helper. The workflow runs
only when dispatched, serialises signing jobs and does not cache Apple sessions or
upload signing files as artefacts.

The runner joins Tailscale as an ephemeral `tag:ephemeral` device using
workload identity federation. Homelab declares the federated identity restricted
to `maxexcloo/signtools-builder` on `main`, with the `auth_keys` write scope and
that tag. After applying its reviewed plan, use the
`github_identity` output to set repository secrets `TS_OAUTH_CLIENT_ID`
from `client_id` and `TS_AUDIENCE` from `audience`, without printing their values.
The action logs the device out after the job.
The connection check requires private DNS results, trusted HTTPS and a 401 response
from the unauthenticated UI before signing begins.

Tailnet policy is owned by `homelab/data/access.yaml` and `homelab/tailscale.tf`.
Ephemeral devices are excluded from the broad tagged-device grant and receive only TCP
port 443 access to the discovered `mbk` gateway addresses. The gateway is shared by other
private applications, so this grants network access to its HTTPS listener, with
application authentication providing the remaining separation. Verify the policy
and private DNS resolution in the first workflow run.

Create a fine-grained GitHub token restricted to the builder repository with
Actions and Secrets read/write permissions. SignTools sets `SECRET_KEY` and
`SECRET_URL` itself at startup; do not copy them manually. Use a zero-spend Actions
budget with usage blocking if signing must stop when the included allowance runs
out. The account's other private workflows share that allowance.

## Credentials

The `SignTools` 1Password item supplies these fields:

| Field                    | Purpose                                                   |
| ------------------------ | --------------------------------------------------------- |
| `apple-account-name`     | Paid Apple developer account email                        |
| `apple-account-password` | Apple account password; signing may prompt for 2FA        |
| `certificate-base64`     | Base64-encoded exported `.p12`, including its private key |
| `certificate-password`   | Password protecting the `.p12`                            |
| `github-token`           | Builder repository token                                  |
| `password`               | Generated web UI password                                 |
| `username`               | Web UI username                                           |

Populate credentials through local credential tools without printing their values.
The signing profile is mounted read-only with a stable `developer` ID, so saved
apps retain their profile association across restarts. The application rewrites
its runtime configuration, including the GitHub token and web password, in a
memory-backed `/tmp`; uploaded apps remain on the retained NFS claim. Restart the
workload after credential changes because SignTools reads them at startup.

## Access & Trial

Use SignTools' built-in basic authentication. Worker endpoints use its generated
bearer key, while app download and installation links are accessible to devices
that can reach the private gateway and have their URLs. An additional blanket
authentication layer would interrupt worker callbacks and iOS installation.
The iPhone needs LAN or Tailscale connectivity while uploading and installing;
the GitHub runner uses Tailscale for its callbacks. Keep trusted HTTPS enabled
for iOS OTA installation. There is no public route or Cloudflare tunnel for this app.

After deployment, verify unauthenticated UI access is rejected, authenticated
uploads trigger the private workflow, and an IPA with the required tweaks signs
and installs successfully. Test app extensions and retained data before replacing
an existing installation or removing SideStore.

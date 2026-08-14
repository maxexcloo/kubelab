# Talos configuration

These are standard Talos machine-configuration patches. They contain no Talos
PKI, Tailscale auth key, kubeconfig, machine address, or disk selection.

The base configuration is generated outside Git and merged with:

- `common.yaml`: the shared single-node, CNI, OIDC, and host-DNS choices.
- `au.yaml`: home cluster name, topology labels, and CIDRs.
- `au-oci.yaml`: OCI cluster name, topology labels, and CIDRs.

## Why patches rather than complete configuration?

`talosctl gen config` creates a cluster CA, etcd CA, bootstrap tokens, and
client credentials. A complete generated file is therefore a secret. Patches
keep the choices we want to review in Git while the secret-bearing result lives
in 1Password and a temporary operator directory.

## Image Factory

`schematic.yaml` asks the official Image Factory for the Tailscale extension.
The factory selects the extension build compatible with Talos `v1.13.8`; it
does not use a floating extension version. Uploading identical content returns
the same content-addressed schematic ID:

```shell
curl --fail --show-error --silent \
  --data-binary @talos/schematic.yaml \
  https://factory.talos.dev/schematics
```

Record the returned ID in the reviewed bootstrap command and use:

```text
factory.talos.dev/metal-installer/SCHEMATIC_ID:v1.13.8
```

The initial image contains Tailscale only. NFSv4 needs no extra user-space
extension for the static-volume trial. Add `siderolabs/iscsi-tools` through a
separate schematic and Talos upgrade only when the iSCSI CSI evaluation begins.

## Generate the home configuration

First verify that the selected node IP is reserved in UniFi, that the CIDRs in
`au.yaml` do not overlap any existing network, and that the installation disk
shown in Talos maintenance mode is disposable. Then generate into a temporary,
encrypted or access-controlled directory:

```shell
talosctl gen secrets --output-file /secure/path/au-secrets.yaml

talosctl gen config au https://AU_NODE_IP:6443 \
  --additional-sans AU_NODE_IP \
  --config-patch @talos/patches/common.yaml \
  --config-patch @talos/patches/au.yaml \
  --install-disk CONFIRMED_INSTALL_DISK \
  --install-image factory.talos.dev/metal-installer/SCHEMATIC_ID:v1.13.8 \
  --kubernetes-version 1.36.3 \
  --output /secure/path/au \
  --talos-version v1.13.8 \
  --with-docs=false \
  --with-examples=false \
  --with-secrets /secure/path/au-secrets.yaml
```

Do not copy the generated output into this repository. Before applying it:

```shell
talosctl validate --config /secure/path/au/controlplane.yaml --mode metal
talosctl get disks --insecure --nodes AU_NODE_IP
```

The home VM is the learning target. Applying configuration, bootstrapping etcd,
or generating `au-oci` configuration is a later reviewed live step, not part of
repository validation.

## Tailscale secret patch

The Tailscale extension needs a secret auth key at first enrolment. Create a
separate uncommitted `ExtensionServiceConfig` document from the 1Password item
and merge it only into the generated machine configuration. The committed
schematic installs the binary but intentionally contains no tailnet credential.

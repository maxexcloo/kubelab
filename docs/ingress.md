# Application Ingress

Application routes and DNS records are workload-owned. Cluster wildcard DNS,
Cloudflare tunnels, stable tunnel targets, and direct-public targets are
bootstrapped by `homelab`.

## Access Modes

| Mode          | Gateway         | DNS target                    | Cloudflare proxy |
| ------------- | --------------- | ----------------------------- | ---------------- |
| Direct public | `public-direct` | `public.<cluster>.excloo.dev` | Per route        |
| Internal      | `private`       | Cluster Tailscale wildcard    | No record        |
| Tunnel public | `public-tunnel` | `tunnel.<cluster>.excloo.dev` | Required         |

Only `syd` currently has a direct-public Gateway. Both clusters have a tunnel
Gateway. Each cluster certificate covers `*.excloo.com` and its cluster
wildcard so established application names remain valid during migration.
Private routes are never read by ExternalDNS.

## Public Route Contract

A public application namespace must carry
`gateway.excloo.dev/public-access: "true"`. Its `HTTPRoute` must:

- attach to exactly one public Gateway;
- carry `gateway.excloo.dev/public-access: "true"` so ExternalDNS can see it;
- set `external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"` for tunnel
  ingress, or explicitly choose the desired proxy mode for direct ingress; and
- list only the application hostnames in `spec.hostnames`.

ExternalDNS creates or updates `A`, `AAAA`, and `CNAME` records within
`excloo.com` and `excloo.dev`. It uses the `noop` registry so an explicitly
labelled route can adopt and overwrite an existing application record during a
cutover. Its `upsert-only` policy leaves DNS records in place when a route is
removed; delete them only as part of an explicitly reviewed cutover or
retirement.

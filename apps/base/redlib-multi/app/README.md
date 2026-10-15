# Redlib Multi

A small self-hosted editor for Redlib multireddit links. Each path stores a separate list on the server, available across devices. Subreddit names are automatically lowercased, sorted and deduplicated. Add names, `r/` links or existing multi links; remove or filter communities and copy the resulting feed link.

## Run

Requires Node.js 24 or newer. No third-party dependencies are needed.

```sh
npm start
```

Open `http://127.0.0.1:3000`, enter a **List Name** and select **Open List**. You can also open a chosen path such as `/australia-news` directly. Existing names load their saved list; new names start empty and the first change saves the list. Names are case-sensitive and accept 1–128 letters, numbers, underscores or hyphens; `health` is reserved. The generated feed uses `https://reddit.excloo.com/r/australia+sydney`.

`DATA_DIRECTORY` defaults to `./data`, `HOST` to `127.0.0.1` and `PORT` to `3000`. Back up the entire data directory using a SQLite-aware backup or stop the app before copying it.

## Self-Host

```sh
docker compose up --build -d
```

The container stores lists in the persistent `data` volume and exposes port 3000 on the host's loopback interface. Configure your HTTPS reverse proxy for `redlib.excloo.com` to forward all paths, including `/api/`, to `http://127.0.0.1:3000`. If the proxy runs in a container or on another host, configure its network access accordingly. DNS and reverse-proxy configuration are managed outside this app.

The Kubelab deployment uses its private HTTPS gateway and private DNS for Tailscale access. Anyone who can reach the app and knows a list name can view and modify that list. Names are not passwords and no list directory is exposed. Existing secret paths continue to work. The app sends no-referrer and no-store headers. The browser title never contains the path. Concurrent edits are rejected with the latest list loaded for retry, rather than silently overwriting changes.

## Verify

```sh
mise run check
```

Checks cover normalisation, path isolation, persistent storage, removal, stale edits, request validation and HTTP routes.

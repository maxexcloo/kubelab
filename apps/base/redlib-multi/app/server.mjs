import { createHash } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { normaliseSubreddits } from "./public/subreddits.mjs";

export function createApp({
  dataDirectory = process.env.DATA_DIRECTORY || "./data",
} = {}) {
  mkdirSync(dataDirectory, { recursive: true });
  const database = new DatabaseSync(resolve(dataDirectory, "lists.sqlite"));
  database.exec(
    "PRAGMA journal_mode = WAL; CREATE TABLE IF NOT EXISTS lists (id TEXT PRIMARY KEY, subreddits TEXT NOT NULL, revision INTEGER NOT NULL)",
  );
  const select = database.prepare(
    "SELECT subreddits, revision FROM lists WHERE id = ?",
  );
  const insert = database.prepare(
    "INSERT OR IGNORE INTO lists (id, subreddits, revision) VALUES (?, ?, 1)",
  );
  const update = database.prepare(
    "UPDATE lists SET subreddits = ?, revision = revision + 1 WHERE id = ? AND revision = ?",
  );
  const assets = new Map(
    [
      ["/", ["index.html", "text/html; charset=utf-8"]],
      ["/app.mjs", ["app.mjs", "text/javascript; charset=utf-8"]],
      ["/style.css", ["style.css", "text/css; charset=utf-8"]],
      ["/subreddits.mjs", ["subreddits.mjs", "text/javascript; charset=utf-8"]],
    ].map(([path, [file, type]]) => [
      path,
      {
        content: readFileSync(new URL(`./public/${file}`, import.meta.url)),
        type,
      },
    ]),
  );
  const server = createServer(async (request, response) => {
    response.setHeader("Cache-Control", "no-store");
    response.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    );
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("X-Robots-Tag", "noindex, nofollow");
    const json = (status, value) => {
      response.writeHead(status, { "Content-Type": "application/json" });
      response.end(JSON.stringify(value));
    };
    try {
      const path = new URL(request.url, "http://localhost").pathname;
      if (path === "/health" && request.method === "GET")
        return json(200, { status: "ok" });
      const match = /^\/api\/lists\/([a-zA-Z0-9_-]{1,128})$/.exec(path);
      if (match) {
        const key = createHash("sha256").update(match[1]).digest("hex");
        const current = () => {
          const row = select.get(key);
          return row
            ? { revision: row.revision, subreddits: JSON.parse(row.subreddits) }
            : { revision: 0, subreddits: [] };
        };
        if (request.method === "GET") return json(200, current());
        if (request.method !== "PUT")
          return json(405, { error: "Method not allowed." });
        if (request.headers["sec-fetch-site"] === "cross-site")
          return json(403, { error: "Cross-site writes are not allowed." });
        if (request.headers["content-type"] !== "application/json")
          return json(415, { error: "Use application/json." });
        let body = "";
        for await (const chunk of request) {
          body += chunk.toString();
          if (Buffer.byteLength(body) > 65536)
            return json(413, { error: "List is too large." });
        }
        let input;
        try {
          input = JSON.parse(body);
        } catch {
          return json(400, { error: "Invalid JSON." });
        }
        if (
          !input ||
          !Number.isSafeInteger(input.revision) ||
          input.revision < 0 ||
          !Array.isArray(input.subreddits) ||
          input.subreddits.length > 1000 ||
          input.subreddits.some((value) => typeof value !== "string")
        )
          return json(400, {
            error: "Provide a revision and up to 1,000 subreddit names.",
          });
        let names;
        try {
          names = normaliseSubreddits(input.subreddits.join(" "));
        } catch (error) {
          return json(400, { error: error.message });
        }
        if (names.length > 1000)
          return json(400, { error: "Use up to 1,000 subreddits." });
        const result =
          input.revision === 0
            ? insert.run(key, JSON.stringify(names))
            : update.run(JSON.stringify(names), key, input.revision);
        if (!result.changes)
          return json(409, {
            ...current(),
            error:
              "This list changed elsewhere. The latest list is loaded; try your change again.",
          });
        return json(200, current());
      }
      if (path.startsWith("/api/"))
        return json(404, { error: "Unknown list path." });
      if (request.method !== "GET" && request.method !== "HEAD")
        return json(405, { error: "Method not allowed." });
      const asset =
        assets.get(path) ||
        (/^\/[a-zA-Z0-9_-]{1,128}$/.test(path) ? assets.get("/") : null);
      if (!asset) return json(404, { error: "Page not found." });
      response.writeHead(200, { "Content-Type": asset.type });
      response.end(request.method === "HEAD" ? undefined : asset.content);
    } catch {
      json(500, { error: "Unable to process this request." });
    }
  });
  server.on("close", () => database.close());
  return server;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const port = Number(process.env.PORT || 3000);
  const host = process.env.HOST || "127.0.0.1";
  createApp().listen(port, host, () =>
    console.log(`Redlib Multi listening on http://${host}:${port}`),
  );
}

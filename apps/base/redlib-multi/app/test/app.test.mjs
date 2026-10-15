import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { multiredditUrl, normaliseSubreddits } from "../public/subreddits.mjs";
import { createApp } from "../server.mjs";

test("normalises names, links and multi links without retaining duplicates", () => {
  assert.deepEqual(
    normaliseSubreddits(
      "Sydney, australia r/SYDNEY\nhttps://reddit.excloo.com/r/Australia+Melbourne/",
    ),
    ["australia", "melbourne", "sydney"],
  );
  assert.equal(
    multiredditUrl(normaliseSubreddits("Sydney+Australia")),
    "https://reddit.excloo.com/r/australia+sydney",
  );
  assert.equal(multiredditUrl([]), null);
  assert.deepEqual(normaliseSubreddits(""), []);
  assert.throws(() => normaliseSubreddits("bad<script>"), /Invalid subreddit/);
  assert.throws(() => normaliseSubreddits("../secrets"), /Invalid subreddit/);
});

test("saves isolated lists, rejects stale edits and survives restarts", async () => {
  const directory = mkdtempSync(join(tmpdir(), "redlib-multi-"));
  let server;
  async function start() {
    server = createApp({ dataDirectory: directory });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    return `http://127.0.0.1:${server.address().port}`;
  }
  async function stop() {
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
  let base = await start();
  const put = (id, body, headers = {}) =>
    fetch(`${base}/api/lists/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
  try {
    assert.deepEqual(await (await fetch(`${base}/api/lists/mysecret`)).json(), {
      revision: 0,
      subreddits: [],
    });
    let response = await put("mysecret", {
      revision: 0,
      subreddits: ["Sydney", "Australia", "sydney"],
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      revision: 1,
      subreddits: ["australia", "sydney"],
    });
    assert.deepEqual(
      await (await fetch(`${base}/api/lists/anothersecret`)).json(),
      { revision: 0, subreddits: [] },
    );
    response = await put("mysecret", {
      revision: 0,
      subreddits: ["melbourne"],
    });
    assert.equal(response.status, 409);
    assert.deepEqual((await response.json()).subreddits, [
      "australia",
      "sydney",
    ]);
    assert.equal(
      (await put("mysecret", { revision: 1, subreddits: ["bad/name"] })).status,
      400,
    );
    assert.equal(
      (
        await put(
          "mysecret",
          { revision: 1, subreddits: ["melbourne"] },
          { "Sec-Fetch-Site": "cross-site" },
        )
      ).status,
      403,
    );
    assert.equal(
      (await put("mysecret", { revision: 1, subreddits: ["sydney"] })).status,
      200,
    );
    const page = await fetch(`${base}/mysecret`);
    assert.equal(page.status, 200);
    assert.equal(page.headers.get("referrer-policy"), "no-referrer");
    assert.match(await page.text(), /Redlib Multi/);
    assert.equal((await fetch(`${base}/api/lists/secret/other`)).status, 404);
    assert.equal((await fetch(`${base}/style.css`)).status, 200);
    await stop();
    base = await start();
    assert.deepEqual(await (await fetch(`${base}/api/lists/mysecret`)).json(), {
      revision: 2,
      subreddits: ["sydney"],
    });
    assert.equal(
      (await put("mysecret", { revision: 2, subreddits: [] })).status,
      200,
    );
    assert.deepEqual(await (await fetch(`${base}/api/lists/mysecret`)).json(), {
      revision: 3,
      subreddits: [],
    });
  } finally {
    await stop();
    rmSync(directory, { force: true, recursive: true });
  }
});

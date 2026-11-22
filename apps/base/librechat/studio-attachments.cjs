const { constants } = require("node:fs");
const { open, realpath } = require("node:fs/promises");
const { createRequire } = require("node:module");
const path = require("node:path");

const fileUnreadable =
  "Studio couldn't read this turn's attached images. Reattach them and try again.";

async function readAttachment(file, owner, roots, send) {
  const [start, area, directory, name, extra] = file.filepath?.split("?")[0].split("/") ?? [];
  const root = area === "images" || area === "uploads" ? roots[area] : undefined;
  if (
    file.source !== "local" ||
    start !== "" ||
    directory !== owner ||
    !root ||
    !name ||
    name === "." ||
    name === ".." ||
    extra !== undefined
  )
    throw new Error(fileUnreadable);

  const ownedRoot = path.join(await realpath(root), owner);
  if ((await realpath(ownedRoot)) !== ownedRoot) throw new Error(fileUnreadable);
  const image = await open(
    path.join(ownedRoot, name),
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
  );
  try {
    const stat = await image.stat();
    if (!stat.size || !stat.isFile()) throw new Error(fileUnreadable);
    const body = image.createReadStream({ autoClose: false });
    try {
      return await send(body, stat.size);
    } finally {
      body.destroy();
    }
  } finally {
    await image.close();
  }
}

function installStudioAttachments({ requests, MCPManager, getFiles, endpoint, key }) {
  const turns = new WeakMap();
  const getContext = requests.getMCPRequestContext;
  requests.getMCPRequestContext = function (req, ...args) {
    const context = getContext.call(this, req, ...args);
    const owner = req?.user?.id;
    const files = req?.body?.files;
    if (
      context &&
      /^[a-f0-9]{24}$/i.test(owner || "") &&
      Array.isArray(files) &&
      files.length &&
      !turns.has(context)
    ) {
      turns.set(context, {
        owner,
        email: req.user.email,
        ids: [...new Set(files.map((file) => file?.file_id))],
        roots: { images: req.config?.paths?.imageOutput, uploads: req.config?.paths?.uploads },
      });
    }
    return context;
  };

  async function importImages(turn, cancel) {
    if (turn.ids.some((id) => typeof id !== "string" || !id)) throw new Error(fileUnreadable);
    const files = await getFiles({ user: turn.owner, file_id: { $in: turn.ids } }, null, {
      file_id: 1,
      filename: 1,
      filepath: 1,
      source: 1,
      type: 1,
      user: 1,
    });
    const owned = new Map(
      (files ?? [])
        .filter((file) => String(file.user) === turn.owner)
        .map((file) => [file.file_id, file]),
    );
    if (turn.ids.some((id) => !owned.has(id))) throw new Error(fileUnreadable);

    const images = turn.ids
      .map((id) => owned.get(id))
      .filter((file) => file.type?.startsWith("image/"));
    const signal = AbortSignal.any([AbortSignal.timeout(15000), ...(cancel ? [cancel] : [])]);
    const assets = [];
    for (const file of images) {
      const asset = await readAttachment(file, turn.owner, turn.roots, async (body, size) => {
        const url = new URL(endpoint);
        url.searchParams.set("name", file.filename);
        const response = await fetch(url, {
          method: "POST",
          headers: {
            authorization: `Bearer ${key}`,
            "content-length": String(size),
            "content-type": "application/octet-stream",
            "x-ai-user-id": turn.owner,
            ...(turn.email && { "x-ai-user-email": turn.email }),
          },
          body,
          duplex: "half",
          redirect: "error",
          signal,
        });
        if (!response.ok) {
          await response.body?.cancel();
          throw new Error(fileUnreadable);
        }
        const { asset } = await response.json();
        if (typeof asset?.id !== "string" || !asset.id) throw new Error(fileUnreadable);
        return asset.id;
      });
      assets.push(asset);
    }
    return assets;
  }

  const callTool = MCPManager.prototype.callTool;
  MCPManager.prototype.callTool = async function (call) {
    const turn = turns.get(call.requestScopedConnections);
    const source = call.serverConfig?.source;
    if (
      !turn ||
      call.serverName !== "studio" ||
      (call.toolName !== "generate" && call.toolName !== "studio-generate") ||
      (source !== "yaml" && source !== "config") ||
      (Array.isArray(call.toolArguments?.reference_asset_ids) &&
        !call.toolArguments.reference_asset_ids.length)
    )
      return callTool.call(this, call);

    if (call.user?.id !== turn.owner) throw new Error(fileUnreadable);
    const signal = call.options?.signal;
    let assets;
    try {
      signal?.throwIfAborted();
      turn.assets ??= importImages(turn, signal);
      assets = await turn.assets;
      signal?.throwIfAborted();
    } catch {
      signal?.throwIfAborted();
      throw new Error(fileUnreadable);
    }
    if (!assets.length) return callTool.call(this, call);
    return callTool.call(this, {
      ...call,
      toolArguments: { ...call.toolArguments, reference_asset_ids: assets },
    });
  };
}

module.exports = { installStudioAttachments };

// npm and its other helpers inherit NODE_OPTIONS but only the server handles turns.
if (path.resolve(process.argv[1] || "") === "/app/api/server/index.js") {
  const app = createRequire("/app/api/package.json");
  app("./config/credentials");
  const { STUDIO_MCP_API_KEY: key, STUDIO_MCP_URL: url } = process.env;
  if (!key || !url)
    throw new Error("Set STUDIO_MCP_API_KEY and STUDIO_MCP_URL for Studio Attachments.");
  installStudioAttachments({
    requests: app("./server/services/MCPRequestContext"),
    MCPManager: app("@librechat/api").MCPManager,
    getFiles: (...args) => app("./models").getFiles(...args),
    endpoint: new URL(`${url}/uploads`),
    key,
  });
}

import { multiredditUrl, normaliseSubreddits } from "./subreddits.mjs";

const $ = (selector) => document.querySelector(selector);
const id = location.pathname.slice(1);
let subreddits = [];
let revision = 0;
let busy = true;

function message(text) {
  $("#status").textContent = text;
}

function render() {
  const url = multiredditUrl(subreddits);
  $("#feed").hidden = !url;
  $("#feed").href = url || "#";
  $("#feed").textContent = url || "";
  $("#empty-feed").hidden = Boolean(url);
  $("#copy-feed").disabled = !url;
  $("#add-button").disabled = busy;
  $("#count").textContent =
    `${subreddits.length} ${subreddits.length === 1 ? "Community" : "Communities"}`;
  const filtered = subreddits.filter((name) =>
    name.includes($("#filter").value.trim().toLowerCase()),
  );
  $("#empty-list").hidden = subreddits.length > 0;
  $("#communities").replaceChildren(
    ...filtered.map((name) => {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.textContent = name;
      link.href = `https://reddit.excloo.com/r/${name}`;
      link.target = "_blank";
      link.rel = "noreferrer";
      const remove = document.createElement("button");
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove r/${name}`);
      remove.disabled = busy;
      remove.addEventListener("click", () =>
        save(subreddits.filter((value) => value !== name)),
      );
      row.append(link, remove);
      return row;
    }),
  );
}

async function request(method, body) {
  const response = await fetch(`/api/lists/${encodeURIComponent(id)}`, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 409) {
      subreddits = result.subreddits;
      revision = result.revision;
    }
    throw new Error(result.error || "Unable to load your list.");
  }
  return result;
}

async function save(next) {
  if (busy) return;
  busy = true;
  message("");
  $("#save-state").textContent = "Saving…";
  render();
  let saved = false;
  try {
    const result = await request("PUT", { revision, subreddits: next });
    subreddits = result.subreddits;
    revision = result.revision;
    $("#save-state").textContent =
      "All changes saved. Your editing link works across devices.";
    saved = true;
  } catch (error) {
    message(error.message);
    $("#save-state").textContent = "Change not saved. Please try again.";
  } finally {
    busy = false;
    render();
  }
  return saved;
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    message("Link copied.");
  } catch {
    message(
      "Copy is unavailable. Select and copy the link from the address bar or feed above.",
    );
  }
}

$("#create").addEventListener("click", () => {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  location.assign(
    `/${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`,
  );
});
$("#copy-editor").addEventListener("click", () => copy(location.href));
$("#copy-feed").addEventListener("click", () =>
  copy(multiredditUrl(subreddits)),
);
$("#filter").addEventListener("input", render);
$("#add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const additions = normaliseSubreddits($("#subreddits").value);
    if (!additions.length) throw new Error("Enter at least one subreddit.");
    const next = [...new Set([...subreddits, ...additions])].sort();
    if (next.length === subreddits.length) {
      message("Those communities are already in your list.");
      return;
    }
    if (await save(next)) $("#subreddits").value = "";
  } catch (error) {
    message(error.message);
  }
});

if (!id) {
  $("#welcome").hidden = false;
} else if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) {
  message(
    "Use a single path containing letters, numbers, underscores or hyphens.",
  );
} else {
  $("#editor").hidden = false;
  render();
  try {
    const result = await request("GET");
    subreddits = result.subreddits;
    revision = result.revision;
    busy = false;
    $("#save-state").textContent = revision
      ? "All changes saved. Your editing link works across devices."
      : "Add your first community to save this list.";
  } catch (error) {
    message(error.message);
    $("#save-state").textContent =
      "Could not load this list. Reload to try again.";
  }
  render();
}

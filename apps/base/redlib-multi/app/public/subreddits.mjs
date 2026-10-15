export function normaliseSubreddits(input) {
  const tokens = String(input)
    .trim()
    .toLowerCase()
    .replace(/https?:\/\/[^\s/]+\/(?:r\/)?/g, "")
    .split(/[\s,+]+/)
    .filter(Boolean)
    .map((value) => value.replace(/^\/?r\//, "").replace(/\/$/, ""));
  const invalid = tokens.filter((value) => !/^[a-z0-9_]{2,21}$/.test(value));
  if (invalid.length)
    throw new Error(
      `Invalid subreddit: ${invalid[0]}. Use 2–21 letters, numbers or underscores.`,
    );
  return [...new Set(tokens)].sort();
}

export function multiredditUrl(subreddits) {
  return subreddits.length
    ? `https://reddit.excloo.com/r/${subreddits.join("+")}`
    : null;
}

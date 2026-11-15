// Preloaded through NODE_OPTIONS. @librechat/agents caps every earlier tool call and result in a
// chat by its widest parallel tool step (16 parallel calls leave window/16) and latches that cap
// for the rest of the chat, so a model loses its own earlier tool inputs, such as Studio prompts.
// Size caps for one step and restart each turn at the full window; real overflow still fades.
const fading = require("/app/node_modules/@librechat/agents/dist/cjs/messages/fading.cjs");

const { createFadingTier, resolveFadingTier } = fading;
fading.resolveFadingTier = (tier, window, signals, maxToolResultChars) =>
  resolveFadingTier(tier, window, { ...signals, toolExchangeWidth: 1 }, maxToolResultChars);
fading.seedFadingTier = (window) => createFadingTier(window);

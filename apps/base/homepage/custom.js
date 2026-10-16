// Keep proxy group identities unique while displaying the inventory's host names.
function formatGroupNames() {
  for (const heading of document.querySelectorAll(".service-group-name")) {
    const name = heading.textContent;
    if (name.endsWith(" (Server)")) {
      heading.textContent = name.slice(0, -" (Server)".length);
    }
  }
}
function observeGroupNames() {
  new MutationObserver(formatGroupNames).observe(document.body, {
    childList: true,
    subtree: true,
  });
  formatGroupNames();
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", observeGroupNames, {
    once: true,
  });
} else {
  observeGroupNames();
}

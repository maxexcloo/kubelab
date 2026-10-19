// The renderer ends Home descriptions with " • <location>"; show each location
// as a tag after the card's name instead. Cards keep the full
// description if Homepage's markup changes.
const LOCATION_SEPARATOR = " • ";

function showLocationTags() {
  for (const description of document.querySelectorAll(".service-description")) {
    const text = description.textContent;
    const index = text.lastIndexOf(LOCATION_SEPARATOR);
    const name = description.closest(".service-name");
    if (index < 0 || !name) {
      continue;
    }
    name.querySelector(":scope > .service-locations")?.remove();
    const tags = document.createElement("div");
    tags.className = "service-locations";
    for (const location of text.slice(index + LOCATION_SEPARATOR.length).split(", ")) {
      const tag = document.createElement("div");
      tag.className = "service-location";
      tag.textContent = location;
      tags.append(tag);
    }
    description.before(tags);
    description.textContent = text.slice(0, index);
  }
}
function observeLocations() {
  new MutationObserver(showLocationTags).observe(document.body, {
    childList: true,
    subtree: true,
  });
  showLocationTags();
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", observeLocations, {
    once: true,
  });
} else {
  observeLocations();
}

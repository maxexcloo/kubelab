// The renderer ends Home descriptions with " • <location>"; show each location
// as a tag beside the card's status instead. Cards keep the full description
// if Homepage's markup changes.
const LOCATION_SEPARATOR = " • ";

function showLocationTags() {
  for (const description of document.querySelectorAll(".service-description")) {
    const text = description.textContent;
    const index = text.lastIndexOf(LOCATION_SEPARATOR);
    const title = description.closest(".service-title");
    if (index < 0 || !title) {
      continue;
    }
    let tags = title.querySelector(".service-tags");
    if (!tags) {
      tags = document.createElement("div");
      tags.className =
        "absolute top-0 right-0 flex flex-row justify-end gap-2 mr-2 z-10 service-tags";
      title.append(tags);
    }
    for (const tag of tags.querySelectorAll(".service-location")) {
      tag.remove();
    }
    for (const location of text.slice(index + LOCATION_SEPARATOR.length).split(", ")) {
      const tag = document.createElement("div");
      tag.className = "service-tag service-location";
      tag.textContent = location;
      tags.prepend(tag);
    }
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

"""Discover upstream model IDs and derive reversible vendor prefixes on demand."""

import asyncio
import fnmatch
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

AGGREGATORS = {"cli-proxy-api", "opencode", "opencode-go", "opencode-zen", "openrouter"}

LABELS = {
    "bento": "Bento",
    "cli-proxy-api": "CLI Proxy API",
    "deepseek": "DeepSeek",
    "google": "Google",
    "opencode": "OpenCode",
    "opencode-go": "OpenCode Go",
    "opencode-zen": "OpenCode Zen",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "xai": "xAI",
}


def label(value):
    return LABELS.get(value.lower(), value.replace("-", " ").replace("_", " ").title())


def display_name(prefix, model):
    identifier = model["id"]
    vendor = identifier.split("/", 1)[0] if "/" in identifier else model.get("owned_by", "")
    name = next(
        (model[field] for field in ("name", "display_name", "normalized_name")
         if isinstance(model.get(field), str) and model[field].strip()),
        None,
    )
    if not name:
        name = identifier.rsplit("/", 1)[-1]
        name = re.sub(r"(claude-(?:sonnet|opus|haiku)-\d+)-(\d+)", r"\1.\2", name)
        name = name.replace("-", " ").replace("_", " ").title()
        for original, replacement in (
            ("Deepseek", "DeepSeek"), ("Fp8", "FP8"),
            ("Gpt ", "GPT-"),
        ):
            name = name.replace(original, replacement)
    parts = [label(prefix)]
    if prefix in AGGREGATORS and vendor and vendor.casefold() != prefix.casefold():
        parts.append(label(vendor))
    return " · ".join([*parts, name])


def resolve(value):
    if isinstance(value, str) and value.startswith("os.environ/"):
        return os.environ[value.removeprefix("os.environ/")]
    return value


def model_names(prefix, model):
    identifier = model["id"]
    original = f"{prefix}/{identifier}"
    vendor = (model.get("owned_by") or "").strip("/")
    # An upstream namespace, such as OpenRouter's anthropic/, is already useful.
    public = original
    if prefix in AGGREGATORS and vendor and vendor.casefold() != prefix.casefold() and "/" not in identifier:
        public = f"{prefix}/{vendor}/{identifier}"
    return public, original


def permitted(public, original, models, metadata):
    excluded = metadata.get("catalogue_excluded_models", [])
    if any(fnmatch.fnmatchcase(original, pattern) for pattern in excluded):
        return False
    return not models or any(
        fnmatch.fnmatchcase(name, pattern)
        for name in (public, original)
        for pattern in models
    )


def fetch_models(deployment):
    params = deployment["litellm_params"]
    endpoint = resolve(params["api_base"]).rstrip("/")
    credential = resolve(params["api_key"])
    headers = {"Authorization": f"Bearer {credential}"}
    models = []
    page = ""
    for _ in range(20):
        query = {}
        if page:
            query["after"] = page
        url = endpoint + "/models"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
        entries = data.get("data")
        if not isinstance(entries, list):
            raise ValueError("Upstream did not return a model list")
        for model in entries:
            if not isinstance(model.get("id"), str) or not model["id"]:
                raise ValueError("Upstream returned an invalid model ID")
            models.append(model)
        next_page = entries[-1]["id"] if data.get("has_more") and entries else ""
        if not next_page:
            return models
        if next_page == page:
            raise ValueError("Upstream repeated a model page")
        page = next_page
    raise ValueError("Upstream model pagination exceeded 20 pages")


class Catalogue:
    def __init__(self):
        self.cache = {}
        self.locks = {}

    async def entries(self, deployments):
        selected = []
        for deployment in deployments:
            name = deployment["model_name"]
            params = deployment["litellm_params"]
            if not params.get("api_base"):
                continue
            if deployment.get("model_info", {}).get("blocked"):
                continue
            identity = (name, params["api_base"], params["api_key"])
            selected.append((identity, deployment))

        async def refresh(identity, deployment):
            async with self.locks.setdefault(identity, asyncio.Lock()):
                now = time.monotonic()
                previous = self.cache.get(identity, {"expires": 0, "models": []})
                if previous["expires"] > now:
                    return
                if not deployment["model_name"].endswith("/*"):
                    model = deployment["litellm_params"]["model"].split("/", 1)[-1]
                    self.cache[identity] = {"expires": now + 60, "models": [{"id": model}]}
                    return
                try:
                    models = await asyncio.to_thread(fetch_models, deployment)
                except Exception:
                    # Exception strings and URLs can contain upstream credentials.
                    logger.warning("Model discovery failed for %s; retaining its last catalogue", deployment["model_name"])
                    models = previous["models"]
                self.cache[identity] = {"expires": now + 60, "models": models}

        await asyncio.gather(*(refresh(identity, deployment) for identity, deployment in selected))
        entries = {}
        for identity, deployment in selected:
            prefix = deployment["model_name"].rsplit("/", 1)[0]
            for model in self.cache[identity]["models"]:
                public, original = model_names(prefix, model)
                if public in entries and entries[public][0] != original:
                    raise ValueError("Conflicting public model names")
                name = display_name(prefix, model)
                entries[public] = (original, {
                    **model, "created": model.get("created", 0), "display_name": name,
                    "id": public, "name": name, "object": "model",
                    "owned_by": model.get("owned_by", prefix),
                })
        return entries

    async def listing(self, deployments, models, metadata):
        entries = await self.entries(deployments)
        return {
            "object": "list",
            "data": [
                model for public, (original, model) in sorted(entries.items())
                if permitted(public, original, models, metadata)
            ],
        }

    async def translate(self, data, deployments, models, metadata):
        requested = data.get("model", "")
        selected = [deployment for deployment in deployments
                    if requested.startswith(deployment["model_name"].rsplit("/", 1)[0] + "/")]
        entries = await self.entries(selected)
        reverse = {public: original for public, (original, _) in entries.items()}
        original = reverse.get(requested, requested)
        if not permitted(requested, original, models, metadata):
            raise PermissionError("This key cannot access the requested model")
        return {**data, "model": original}

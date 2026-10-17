"""Upstream discovery must preserve routing IDs, labels and key access."""

import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("catalogue", ROOT / "apps/base/litellm/catalogue.py")
catalogue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalogue)


def deployment(prefix="cli-proxy-api", model="openai/*"):
    return {"model_name": prefix + "/*", "litellm_params": {
        "api_base": "https://provider.example/v1", "api_key": "fixture", "model": model,
    }}


class CatalogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_compact_names_route_to_original_and_preserve_request(self):
        models = [{"id": "claude-sonnet-4-6", "owned_by": "antigravity"}]
        instance = catalogue.Catalogue()
        with patch.object(catalogue, "fetch_models", return_value=models):
            listing = await instance.listing([deployment()], ["cli-proxy-api/*"], {})
            row = listing["data"][0]
            self.assertEqual(row["name"], "CLI Proxy API · Antigravity · Claude Sonnet 4.6")
            request = {"model": row["id"], "messages": [{"role": "user", "content": "Hello"}]}
            result = await instance.translate(request, [deployment()], ["cli-proxy-api/*"], {})
            self.assertEqual(result["model"], "cli-proxy-api/claude-sonnet-4-6")
            self.assertEqual(result["messages"], request["messages"])
            self.assertEqual(request["model"], row["id"])

    def test_duplicate_vendor_and_existing_namespace(self):
        self.assertEqual(catalogue.model_names("deepseek", {
            "id": "deepseek-v4-pro", "owned_by": "deepseek",
        })[0], "deepseek/deepseek-v4-pro")
        self.assertEqual(catalogue.model_names("openrouter", {
            "id": "anthropic/claude-sonnet-4.6", "owned_by": "openrouter",
        })[0], "openrouter/anthropic/claude-sonnet-4.6")
        self.assertEqual(catalogue.model_names("bento", {
            "id": "qwen3.8-27b-fp8", "owned_by": "radiance",
        })[0], "bento/qwen3.8-27b-fp8")

    def test_upstream_display_name_is_preserved(self):
        self.assertEqual(catalogue.display_name("deepseek", {
            "id": "deepseek-v4-pro", "owned_by": "deepseek", "name": "DeepSeek V4 Pro",
        }), "DeepSeek · DeepSeek V4 Pro")

    def test_direct_provider_labels_have_two_tiers(self):
        for prefix, model, expected in [
            ("bento", {"id": "qwen3.8-27b-fp8", "owned_by": "radiance"},
             "Bento · Qwen3.8 27B FP8"),
        ]:
            with self.subTest(prefix=prefix):
                self.assertEqual(catalogue.display_name(prefix, model), expected)

    def test_aggregator_labels_retain_the_model_publisher(self):
        self.assertEqual(catalogue.display_name("openrouter", {
            "id": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "owned_by": "openrouter",
        }), "OpenRouter · Anthropic · Claude Sonnet 4.6")

    async def test_excluded_models_cannot_be_listed_or_called(self):
        models = [{"id": "grok-4.20-0309-non-reasoning", "owned_by": "xai"}]
        metadata = {"catalogue_excluded_models": ["cli-proxy-api/grok-4.20-0309-non-reasoning"]}
        instance = catalogue.Catalogue()
        with patch.object(catalogue, "fetch_models", return_value=models):
            self.assertEqual((await instance.listing([deployment()], [], metadata))["data"], [])
            with self.assertRaises(PermissionError):
                await instance.translate({"model": "cli-proxy-api/xai/" + models[0]["id"]},
                                         [deployment()], [], metadata)

    async def test_static_model_does_not_require_discovery(self):
        configured = deployment("fixture", "openai/qwen3.8-27b-fp8")
        configured["model_name"] = "fixture/qwen3.8-27b-fp8"
        with patch.object(catalogue, "fetch_models", side_effect=AssertionError("No discovery")):
            result = await catalogue.Catalogue().listing([configured], [configured["model_name"]], {})
        self.assertEqual(result["data"][0]["id"], configured["model_name"])

    async def test_failure_retains_last_good_catalogue(self):
        instance = catalogue.Catalogue()
        with patch.object(catalogue, "fetch_models", return_value=[{"id": "gpt-6.1-sol", "owned_by": "openai"}]):
            first = await instance.listing([deployment()], [], {})
        for cached in instance.cache.values():
            cached["expires"] = 0
        with patch.object(catalogue, "fetch_models", side_effect=OSError("Unavailable")):
            second = await instance.listing([deployment()], [], {})
        self.assertEqual(first, second)

    async def test_request_only_discovers_its_source(self):
        with patch.object(catalogue, "fetch_models", return_value=[]) as fetch:
            await catalogue.Catalogue().translate({"model": "deepseek/deepseek-v4-pro"},
                                                  [deployment(), deployment("deepseek")], [], {})
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0]["model_name"], "deepseek/*")

    def test_openai_pagination(self):
        pages = [
            {"data": [{"id": "first"}], "has_more": True},
            {"data": [{"id": "second"}], "has_more": False},
        ]
        with patch.object(catalogue.urllib.request, "urlopen",
                          side_effect=[io.StringIO(json.dumps(page)) for page in pages]) as fetch:
            rows = catalogue.fetch_models(deployment())
        self.assertEqual([row["id"] for row in rows], ["first", "second"])
        self.assertEqual(fetch.call_args.args[0].full_url, "https://provider.example/v1/models?after=first")

    async def test_inference_scope_filters_other_sources(self):
        with patch.object(catalogue, "fetch_models", return_value=[{"id": "example"}]):
            result = await catalogue.Catalogue().listing(
                [deployment(), deployment("deepseek")], ["deepseek/*"], {},
            )
        self.assertEqual([row["id"] for row in result["data"]], ["deepseek/example"])


if __name__ == "__main__":
    unittest.main()

"""Exercise the gateway hooks without installing LiteLLM's dependency tree."""

import importlib.util
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parent.parent


class HTTPException(Exception):
    def __init__(self, *, status_code, detail):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class HookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.router = SimpleNamespace(routes=[])

        def get(path):
            def register(endpoint):
                self.router.routes.append(SimpleNamespace(endpoint=endpoint, path=path))
                return endpoint
            return register

        self.router.get = get
        self.existing = SimpleNamespace(path="/v1/models")
        self.proxy = SimpleNamespace(
            app=SimpleNamespace(router=SimpleNamespace(routes=[self.existing])),
            llm_router=SimpleNamespace(model_list=[{"model_name": "fixture/*"}]),
            user_api_key_auth=Mock(),
        )
        self.proxy.app.include_router = Mock(
            side_effect=lambda router: self.proxy.app.router.routes.extend(router.routes)
        )
        self.catalogue = SimpleNamespace(listing=AsyncMock(), translate=AsyncMock())
        modules = {
            "catalogue": SimpleNamespace(Catalogue=lambda: self.catalogue),
            "fastapi": SimpleNamespace(
                APIRouter=lambda: self.router,
                Depends=lambda dependency: SimpleNamespace(dependency=dependency),
                HTTPException=HTTPException,
            ),
            "litellm": SimpleNamespace(),
            "litellm.integrations": SimpleNamespace(),
            "litellm.integrations.custom_logger": SimpleNamespace(CustomLogger=object),
            "litellm.proxy": SimpleNamespace(proxy_server=self.proxy),
        }
        spec = importlib.util.spec_from_file_location("gateway_hooks", ROOT / "apps/base/litellm/hooks.py")
        self.hooks = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.hooks)
        self.key = SimpleNamespace(metadata={"catalogue_excluded_models": ["fixture/hidden"]},
                                   models=["fixture/*"])

    async def test_model_request_preserves_key_permissions_and_denial(self):
        data = {"model": "fixture/public", "messages": []}
        self.catalogue.translate.return_value = {**data, "model": "fixture/original"}
        result = await self.hooks.callback.async_pre_call_hook(self.key, None, data, "completion")
        self.assertEqual(result["model"], "fixture/original")
        self.catalogue.translate.assert_awaited_once_with(
            data, self.proxy.llm_router.model_list, self.key.models, self.key.metadata,
        )
        self.catalogue.translate.side_effect = PermissionError("Denied")
        with self.assertRaises(HTTPException) as raised:
            await self.hooks.callback.async_pre_call_hook(self.key, None, data, "completion")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "Denied")

    async def test_mcp_and_requests_without_models_bypass_catalogue_permissions(self):
        for call_type, data in (
            ("call_mcp_tool", {"model": "heiss", "name": "fixture"}),
            ("list_mcp_tools", {"model": "heiss"}),
            ("completion", {"messages": []}),
        ):
            with self.subTest(call_type=call_type, data=data):
                result = await self.hooks.callback.async_pre_call_hook(self.key, None, data, call_type)
                self.assertIs(result, data)
        self.catalogue.translate.assert_not_awaited()

    async def test_model_routes_take_precedence_and_keep_authentication(self):
        self.hooks.install()
        routes = self.proxy.app.router.routes
        self.assertEqual([route.path for route in routes], ["/models", "/v1/models", "/v1/models"])
        self.assertIs(routes[-1], self.existing)
        for route in routes[:2]:
            dependency = inspect.signature(route.endpoint).parameters["key"].default
            self.assertIs(dependency.dependency, self.proxy.user_api_key_auth)
            self.catalogue.listing.return_value = {"data": [{"id": "fixture/public"}]}
            result = await route.endpoint(self.key)
            self.assertEqual(result, self.catalogue.listing.return_value)
            self.catalogue.listing.assert_awaited_with(
                self.proxy.llm_router.model_list, self.key.models, self.key.metadata,
            )


if __name__ == "__main__":
    unittest.main()

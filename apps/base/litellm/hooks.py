"""Attach catalogue discovery to LiteLLM's startup and request hooks."""

from fastapi import APIRouter, Depends, HTTPException
from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy import proxy_server

from catalogue import Catalogue

catalogue = Catalogue()


def deployments():
    router = proxy_server.llm_router
    return [] if router is None else router.model_list


class ModelCatalogue(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type in {"call_mcp_tool", "list_mcp_tools"} or "model" not in data:
            return data
        try:
            return await catalogue.translate(
                data, deployments(), user_api_key_dict.models,
                user_api_key_dict.metadata or {},
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error


callback = ModelCatalogue()


def install():
    router = APIRouter()

    @router.get("/v1/models")
    @router.get("/models")
    async def models(key=Depends(proxy_server.user_api_key_auth)):
        return await catalogue.listing(deployments(), key.models, key.metadata or {})

    # FastAPI matches routes in order; the discovered catalogue takes precedence.
    proxy_server.app.include_router(router)
    routes = proxy_server.app.router.routes
    routes[:0] = [routes.pop() for _ in router.routes][::-1]

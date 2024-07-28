import inspect
from typing import TYPE_CHECKING, Type, TypeVar, Union, cast

import httpx
import pydantic
from httpx import URL
from loguru import logger

from slark._constants import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT
from slark.types._request.request import FinalRequestOptions, RequestOptions
from slark.types.exceptions import errors as err

if TYPE_CHECKING:
    from slark.types.response import BaseResponse

ResponseT = TypeVar(
    "ResponseT",
    bound=Union[
        None,
        dict,
        list,
        "BaseResponse",
    ],
)


class AsyncAPIClient:
    _client: httpx.AsyncClient
    max_retries: int
    auth_headers: dict

    def __init__(
        self,
        *,
        base_url: str | URL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        proxies: httpx._types.ProxyTypes | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, proxies=proxies
        )
        self.max_retries = max_retries

    async def get_auth_headers(self) -> dict:
        return {}

    @property
    def default_headers(self) -> dict:
        return {
            "Accept": "application/json",
        }

    async def _build_headers(self, options: FinalRequestOptions) -> httpx.Headers:
        headers = {**self.default_headers, **options.headers}
        if not options.no_auth:
            auth_headers = await self.get_auth_headers()
            headers = {**headers, **auth_headers}
        return httpx.Headers(headers)

    async def _build_request(self, options: FinalRequestOptions) -> httpx.Request:
        headers = await self._build_headers(options)
        content_type = headers.get("Content-Type")
        if options.json_data is not None and content_type is None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        kwargs = {}
        if options.timeout is not None:
            kwargs["timeout"] = options.timeout
        return self._client.build_request(
            method=options.method,
            url=options.url,
            params=options.params,
            headers=headers,
            json=options.json_data,
            **kwargs,
        )

    def _make_status_error_from_response(
        self, response: httpx.Response
    ) -> err.LarkException:
        try:
            body = response.json()
            if "code" not in body:
                raise ValueError("No code in response")
        except Exception as e:
            return err.BadResponseError(msg=str(e), context={"response": response.text})
        return err.LarkException(
            code=body["code"], msg=body.get("msg", ""), context=body
        )

    async def request(
        self,
        cast_to: Type[ResponseT],
        options: FinalRequestOptions,
        remaining_retries: int | None = None,
    ) -> ResponseT:
        request = await self._build_request(options)
        try:
            response = await self._client.send(request)
        except httpx.TimeoutException as e:
            logger.debug(f"Request timed out: {e}")
            raise err.APITimeoutError(context={"request": request}) from e
        except Exception as e:
            logger.debug(f"Request failed: {e}")
            raise err.APIConnectionError(context={"request": request}) from e

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.debug(f"Request failed: {e}")
            raise self._make_status_error_from_response(e.response) from e
        if response.json()["code"] != 0:
            raise self._make_status_error_from_response(response)
        try:
            if inspect.isclass(cast_to) and issubclass(cast_to, pydantic.BaseModel):
                return cast(ResponseT, cast_to.model_validate(response.json()))
            return cast(ResponseT, response.json())
        except Exception as e:
            raise err.BadResponseError(str(e), context={"response": response.json()})

    async def get(
        self,
        path: str,
        *,
        cast_to: Type[ResponseT],
        options: RequestOptions = {},
    ) -> ResponseT:
        opts = FinalRequestOptions(method="get", url=path, **options)
        return await self.request(cast_to, opts)

    async def post(
        self,
        path: str,
        *,
        body: dict | None = None,
        cast_to: Type[ResponseT],
        options: RequestOptions = {},
    ) -> ResponseT:
        opts = FinalRequestOptions(method="post", json_data=body, url=path, **options)
        return await self.request(cast_to, opts)

    async def put(
        self,
        path: str,
        *,
        body: dict | None = None,
        cast_to: Type[ResponseT],
        options: RequestOptions = {},
    ) -> ResponseT:
        opts = FinalRequestOptions(method="put", json_data=body, url=path, **options)
        return await self.request(cast_to, opts)

    async def delete(
        self,
        path: str,
        *,
        cast_to: Type[ResponseT],
        options: RequestOptions = {},
    ) -> ResponseT:
        opts = FinalRequestOptions(method="delete", url=path, **options)
        return await self.request(cast_to, opts)

    async def patch(
        self,
        path: str,
        *,
        body: dict | None = None,
        cast_to: Type[ResponseT],
        options: RequestOptions = {},
    ) -> ResponseT:
        opts = FinalRequestOptions(method="patch", json_data=body, url=path, **options)
        return await self.request(cast_to, opts)
"""
The apiclient module implements the BlockperfApiClient class to access the api.
Its rather simple by only providing basic http verbs to use.

Example Usage:

async with BlockperfApiClient(base_url, secret) as client:
    data = await client.get("users")


# With Pydantic models
class User(BaseModel):
    id: int
    name: str

async with BlockperfApiClient(...) as client:
    user = await client.get("users/1", response_model=User)
    # user is typed as User

    new_user = User(id=0, name="Alice")
    created = await client.post("users", data=new_user, response_model=User)


"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import BaseModel

from openblockperf.discovery import API_REQUEST_RETRIES, API_REQUEST_TIMEOUT, EndpointPool
from openblockperf.errors import ApiConnectionError, ApiError
from openblockperf.logging import logger


class BlockperfApiBase:
    """
    An async client for the openblockperf backend.

    This client handles authentication and provides methods to make
    async requests with automatic JSON/Pydantic conversion.

    """

    def __init__(
        self,
        pool: EndpointPool,
        api_key: str | None,
        hostname: str | None = None,
        timeout: float = API_REQUEST_TIMEOUT,
        retries: int = API_REQUEST_RETRIES,
        **httpx_kwargs,
    ):
        self.pool = pool
        self.hostname = hostname
        self.api_key = api_key
        self.token = None
        self.token_expiry = 0
        self._client: httpx.AsyncClient | None = None
        self._client_base: str | None = None
        self.httpx_kwargs = httpx_kwargs
        self.timeout = timeout
        self.retries = retries

    @property
    def attempts_per_host(self) -> int:
        """Initial attempt plus the configured extra retries."""
        return 1 + self.retries

    @property
    def full_api_url(self) -> str:
        current = self.pool.current
        if current is not None:
            return current.base_url
        return self._client_base or ""

    async def _ensure_client(self) -> httpx.AsyncClient:
        await self.pool.ensure_ready()
        current = self.pool.current
        if current is None:
            raise ApiConnectionError("No API endpoint available")
        if self._client is None or self._client_base != current.base_url:
            await self.close()
            self._client = httpx.AsyncClient(
                base_url=current.base_url,
                timeout=httpx.Timeout(self.timeout),
                **self.httpx_kwargs,
            )
            self._client_base = current.base_url
        return self._client

    async def rebuild_client(self) -> None:
        """Drop the cached httpx client so the next request uses the current edge."""
        await self.close()

    @property
    def client(self):
        """Return the cached client. Prefer _ensure_client() in async code."""
        if not self._client:
            raise RuntimeError("API client is not initialized; await a request first")
        return self._client

    async def close(self):
        """Close the client if there is one"""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._client_base = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> httpx.Response | None:
        """Make an authenticated request to the API.

        Transport timeouts and connection errors are retried on the same host,
        then the service-mode pool fails over. HTTP 4xx and 5xx never fail over.
        """
        headers = kwargs.pop("headers", {})
        if not self.api_key:
            logger.warning("No ApiKey found!")
        headers["X-Api-Key"] = self.api_key or ""
        headers["X-Hostname"] = self.hostname
        # Relative path so httpx keeps /{network}/api/v0/ from the base URL.
        request_path = endpoint.lstrip("/")
        attempts_on_host = 0

        while True:
            client = await self._ensure_client()
            current = self.pool.current
            try:
                logger.debug(
                    f"{method.upper()}: {request_path}",
                    hostname=self.hostname,
                    url=self.full_api_url,
                    kwargs=kwargs,
                )
                response = await client.request(
                    method,
                    request_path,
                    headers=headers,
                    **kwargs,
                )
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"API request failed: {e.response.status_code} {e.response.reason_phrase}",
                    url=str(e.response.url),
                )
                raise ApiError(f"The API returned an error: {e}") from e

            except httpx.RequestError as e:
                attempts_on_host += 1
                logger.warning(
                    "API transport error",
                    error=repr(e),
                    url=self.full_api_url,
                    attempt=attempts_on_host,
                    max_attempts=self.attempts_per_host,
                )
                if attempts_on_host < self.attempts_per_host:
                    continue
                if not self.pool.service_mode:
                    raise ApiConnectionError(f"Failed to connect to API: {e}") from e
                if current is None:
                    raise ApiConnectionError(f"Failed to connect to API: {e}") from e
                await self.close()
                await self.pool.failover_from(current)
                attempts_on_host = 0

    def _parse_response[T](
        self,
        response: httpx.Response | None,
        response_model: type[T] | None = None,
    ) -> T | Mapping[str, Any]:
        """Parse response JSON into Pydantic model or dict."""
        if not response:
            return {}
        data = response.json()
        # Parse data into response_model only if we have both
        if response_model and data:
            return response_model.model_validate(data)
        return data

    # To all http methods provide an endpoint and optonaly a response mode.
    # The response will be validated against that model if present.
    async def get[T](
        self,
        endpoint: str,
        response_model: type[T] | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform GET request to the API."""
        response = await self._make_request("GET", endpoint, **kwargs)
        return self._parse_response(response, response_model)

    async def post[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform POST request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("POST", endpoint, **kwargs)
        return self._parse_response(response, response_model)

    async def put[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform PUT request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("PUT", endpoint, **kwargs)
        return self._parse_response(response, response_model)

    async def patch[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform PATCH request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("PATCH", endpoint, **kwargs)
        return self._parse_response(response, response_model)

    async def delete[T](
        self,
        endpoint: str,
        response_model: type[T] | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any] | None:
        """Perform DELETE request to the API."""
        response = await self._make_request("DELETE", endpoint, **kwargs)
        if response.status_code == HTTPStatus.NO_CONTENT:
            return None
        return self._parse_response(response, response_model)

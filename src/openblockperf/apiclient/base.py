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

import asyncio
import contextlib
import time
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import BaseModel

from openblockperf.errors import ApiConnectionError
from openblockperf.logging import logger

_RETRY_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)
_BACKOFF_BASE: float = 5.0
_BACKOFF_MAX: float = 300.0
_MAX_ATTEMPTS: int = 50  # None for infinite
_stop_event: asyncio.Event | None = None


def _backoff(attempt: int) -> float:
    """Calculate backoff time (to wait)."""
    return min(_BACKOFF_BASE * 2**attempt, _BACKOFF_MAX)


def set_stop_event(event: asyncio.Event) -> None:
    """Allows to provide the _stop_event from outside this module."""
    global _stop_event  # noqa: PLW0603
    _stop_event = event


class BlockperfApiBase:
    """
    An async client for the openblockperf backend.

    This client handles authentication and provides methods to make
    async requests with automatic JSON/Pydantic conversion.

    """

    def __init__(
        self,
        full_api_url: str,
        api_key: str,
        hostname: str | None = None,
        timeout: float = 20.0,
        stop_event: asyncio.Event | None = None,
        **httpx_kwargs,
    ):
        # Initialize from settings instance or create new one
        # Allows CLI overrides to flow through to API client

        self.full_api_url = full_api_url
        self.hostname = hostname
        self.api_key = api_key
        self.token = None
        self.token_expiry = 0
        self._client: httpx.AsyncClient | None = None
        self.httpx_kwargs = httpx_kwargs
        self.timeout = timeout
        self.stop_event = stop_event or asyncio.Event()

    @property
    def client(self):
        """Return the client and initialize class cache"""
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.full_api_url,
                **self.httpx_kwargs,
            )
        return self._client

    async def close(self):
        """Close the client if there is one"""
        if self._client:
            await self._client.aclose()

    async def __aenter__(self):
        # call client once to ensure it is created
        _ = self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> httpx.Response | None:
        """Make an authenticated request to the API."""
        attempts = 0
        while True:
            try:
                logger.info("Make request", api_id=id(self))
                headers = kwargs.pop("headers", {})
                if not self.api_key:
                    logger.warning("No ApiKey found!")
                headers["X-Api-Key"] = self.api_key or ""
                headers["X-Hostname"] = self.hostname
                logger.debug(f"{method.upper()}: {endpoint}", hostname=self.hostname, kwargs=kwargs)
                response = await self.client.request(
                    method,
                    f"/{endpoint.lstrip('/')}",
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                response.raise_for_status()
            # Catch all exceptions, that i want to retry on
            except _RETRY_EXCEPTIONS as e:
                if _MAX_ATTEMPTS is not None and attempts >= _MAX_ATTEMPTS:
                    raise ApiConnectionError(f"Failed to connect to API after {attempts} attempts: {e}") from e
                delay = _backoff(attempts)
                logger.warning(f"API Error {type(e).__name__!r}, retrying in {delay}s (attempt {attempts + 1})")

                # Setup stop_task to be able to SIGTERM the process while waiting for delay
                stop_task = asyncio.create_task(_stop_event.wait())
                sleep_task = asyncio.create_task(asyncio.sleep(delay))
                await asyncio.wait([sleep_task, stop_task], return_when=asyncio.FIRST_COMPLETED)
                for t in (sleep_task, stop_task):
                    if not t.done():
                        t.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await t
                if _stop_event.is_set():
                    raise ApiConnectionError("Shutdown during API retry") from e

                attempts += 1

            # except httpx.HTTPStatusError as e:
            #    logger.error(
            #        f"API request failed: {e.response.status_code} {e.response.reason_phrase}", url=e.response.url
            #    )
            #    raise ApiError(f"The API returned an error: {e}") from e
            # except httpx.TimeoutException as e:
            #    raise ApiError(f"API request timed out: {self.full_api_url}") from None
            # except httpx.ConnectError as e:
            #    raise ApiConnectionError(f"Failed to connect to API: {e}") from e
            else:
                return response

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

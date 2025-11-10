"""
The apiclient module implements the BlockperfApiClient class to access the api.
Its rather simple by only providing basic http verbs to use.

Example Usage:

async with BlockperfApiClient(base_url, clientid, secret) as client:
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

import time
from collections.abc import Mapping
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

from blockperf.clientid import get_clientid
from blockperf.config import settings
from blockperf.errors import ApiConnectionError, ApiError


class BlockperfApiBase:
    """
    An async client for the openblockperf backend.

    This client handles authentication and provides methods to make
    async requests with automatic JSON/Pydantic conversion.

    Usage:
        async with BlockperfApiBase(base_url, clientid, client_secret) as client:
            result = await client.get("endpoint", response_model=MyModel)
    """

    def __init__(
        self,
        timeout: float = 30.0,
        **httpx_kwargs,
    ):
        # Automagically initialises the api from the settings.
        # Eventuallly i would like to move this up into the client such that
        # the Base api is not depending on settings but only its inputs.
        # The client should handle "the settings" and provide correct values
        self._url = f"{settings().api_base_url}:{settings().api_base_port}{settings().api_base_path}"
        self.clientid: str | None = settings().api_clientid
        self.client_secret: str | None = settings().api_client_secret
        self.api_key = settings().api_key
        self._token: str | None = None
        self._token_expiry: float = 0
        self._client: httpx.AsyncClient | None = None
        self._httpx_kwargs = httpx_kwargs
        self._timeout = timeout

    @property
    def client(self):
        """Return the client and initialize class cache"""
        if not self._client:
            print("Creating client")
            self._client = httpx.AsyncClient(
                base_url=self._url,
                timeout=self._timeout,
                **self._httpx_kwargs,
            )
        return self._client

    async def close(self):
        """Close the client if there is one"""
        if self._client:
            print("Closing client")
            await self._client.aclose()

    # Provide context manager
    async def __aenter__(self):
        _ = self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an authenticated request to the API."""
        # await self._ensure_valid_token()
        try:
            headers = kwargs.pop("headers", {})
            if not self.api_key:
                raise RuntimeError("No api key found")
            headers["X-Api-Key"] = self.api_key
            headers["X-Client-Id"] = get_clientid()

            response = await self.client.request(
                method,
                f"/{endpoint.lstrip('/')}",
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            # if response.status_code == 401:
            #    # Token expired, retry once with new token
            #    self._token = None
            #    await self._ensure_valid_token()
            #    headers["Authorization"] = f"Bearer {self._token}"
            #    response = await self.client.request(
            #        method,
            #        f"/{endpoint.lstrip('/')}",
            #        headers=headers,
            #        **kwargs,
            #    )
            raise ApiError(
                f"API request failed: {e.response.status_code} {e.response.reason_phrase}"
            ) from e
        except httpx.TimeoutException as e:
            raise ApiError(f"API request timed out: {e}") from e
        except httpx.ConnectError as e:
            raise ApiConnectionError(f"Failed to connect to API: {e}") from e

        return response

    def _parse_response[T](
        self,
        response: httpx.Response,
        response_model: type[T] | None = None,
    ) -> T | Mapping[str, Any]:
        """Parse response JSON into Pydantic model or dict."""
        data = response.json()
        if response_model:
            return response_model.model_validate(data)
        return data

    async def _get_challenge(self) -> str:
        """Get a challenge from the server for authentication."""
        response = await self.client.get(
            "/auth/challenge",
            params={"clientid": self.clientid},
        )
        response.raise_for_status()

        return response.json()["challenge"]

    def _solve_challenge(self, challenge: str) -> str:
        """
        Solve the challenge using client secret.
        Real implementation depends on API requirements.
        """
        return f"{challenge}:{self.client_secret}"

    async def _authenticate(self) -> None:
        """Perform the challenge-response authentication flow."""
        challenge = await self._get_challenge()
        solution = self._solve_challenge(challenge)

        response = await self.client.post(
            "/auth/token",
            json={
                "clientid": self.clientid,
                "challenge": challenge,
                "solution": solution,
            },
        )
        response.raise_for_status()

        token_data = response.json()
        self._token = token_data["token"]
        self._token_expiry = time.time() + token_data.get("expires_in", 3600)

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid token, requesting a new one if needed."""
        if not self._token or time.time() >= self._token_expiry:
            await self._authenticate()

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
        if response.status_code == 204:
            return None
        return self._parse_response(response, response_model)

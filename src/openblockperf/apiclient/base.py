"""
The apiclient module implements the BlockperfApiClient class to access the api.
Its rather simple by only providing basic http verbs to use.

Example Usage:

async with BlockperfApiClient(base_url, client_id, secret) as client:
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
from http import HTTPStatus
from typing import Any

import httpx
from pydantic import BaseModel

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
        full_api_url: str,
        api_key: str,
        client_id: str | None = None,
        timeout: float = 10.0,
        **httpx_kwargs,
    ):
        # Initialize from settings instance or create new one
        # Allows CLI overrides to flow through to API client

        self.full_api_url = full_api_url
        self.client_id = client_id
        self.api_key = api_key
        self.token = None
        self.token_expiry = 0
        self._client: httpx.AsyncClient | None = None
        self.httpx_kwargs = httpx_kwargs
        self.timeout = timeout

    @property
    def client(self):
        """Return the client and initialize class cache"""
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self.full_api_url,
                timeout=self.timeout,
                **self.httpx_kwargs,
            )
        return self._client

    async def close(self):
        """Close the client if there is one"""
        if self._client:
            await self._client.aclose()

    # Provide context manager
    async def __aenter__(self):
        # call client once to ensure it is created
        _ = self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        base_url: str | None = None,
        **kwargs,
    ) -> httpx.Response | None:
        """Make an authenticated request to the API.

        The http client is lazy loaded through the property client(). To not
        poison its state with a single call to a different base_url, a temporary
        client is created if there is a temporary client provided.
        """
        # await self._ensure_valid_token()
        try:
            headers = kwargs.pop("headers", {})
            headers["X-Api-Key"] = self.api_key or ""
            headers["X-Client-Id"] = self.client_id
            if base_url:
                async with httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self.timeout,
                    **self.httpx_kwargs,
                ) as tmp_client:
                    response = await tmp_client.request(
                        method,
                        f"/{endpoint.lstrip('/')}",
                        headers=headers,
                        **kwargs,
                    )
            else:
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
            #    self.token = None
            #    await self._ensure_valid_token()
            #    headers["Authorization"] = f"Bearer {self.token}"
            #    response = await self.client.request(
            #        method,
            #        f"/{endpoint.lstrip('/')}",
            #        headers=headers,
            #        **kwargs,
            #    )
            logger.error(f"API request failed: {e.response.status_code} {e.response.reason_phrase}", url=e.response.url)
            return None
        except httpx.TimeoutException as e:
            raise ApiError(f"API request timed out: {e}") from e
        except httpx.ConnectError as e:
            raise ApiConnectionError(f"Failed to connect to API: {e}") from e

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

    async def _get_challenge(self) -> str:
        """Get a challenge from the server for authentication."""
        response = await self.client.get(
            "/auth/challenge",
            params={"clientid": self.client_id},
        )
        response.raise_for_status()

        return response.json()["challenge"]

    def _solve_challenge(self, challenge: str) -> str:
        """
        Solve the challenge using client secret.
        Real implementation depends on API requirements.
        """
        return f"{challenge}"

    async def _authenticate(self) -> None:
        """Perform the challenge-response authentication flow."""
        challenge = await self._get_challenge()
        solution = self._solve_challenge(challenge)

        response = await self.client.post(
            "/auth/token",
            json={
                "client_id": self.client_id,
                "challenge": challenge,
                "solution": solution,
            },
        )
        response.raise_for_status()

        token_data = response.json()
        self.token = token_data["token"]
        self.token_expiry = time.time() + token_data.get("expires_in", 3600)

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid token, requesting a new one if needed."""
        if not self.token or time.time() >= self.token_expiry:
            await self._authenticate()

    # To all http methods provide an endpoint and optonaly a response mode.
    # The response will be validated against that model if present.
    async def get[T](
        self,
        endpoint: str,
        response_model: type[T] | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform GET request to the API."""
        response = await self._make_request("GET", endpoint, base_url, **kwargs)
        return self._parse_response(response, response_model)

    async def post[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform POST request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("POST", endpoint, base_url, **kwargs)
        return self._parse_response(response, response_model)

    async def put[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform PUT request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("PUT", endpoint, base_url, **kwargs)
        return self._parse_response(response, response_model)

    async def patch[T](
        self,
        endpoint: str,
        data: BaseModel | None = None,
        response_model: type[T] | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any]:
        """Perform PATCH request to the API."""
        if data:
            kwargs["json"] = data.model_dump(mode="json", exclude_none=True)
        response = await self._make_request("PATCH", endpoint, base_url, **kwargs)
        return self._parse_response(response, response_model)

    async def delete[T](
        self,
        endpoint: str,
        response_model: type[T] | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> T | Mapping[str, Any] | None:
        """Perform DELETE request to the API."""
        response = await self._make_request("DELETE", endpoint, base_url, **kwargs)
        if response.status_code == HTTPStatus.NO_CONTENT:
            return None
        return self._parse_response(response, response_model)

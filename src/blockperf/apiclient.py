import time
from collections.abc import Mapping
from typing import Any

import requests


class BlockperfApiClient:
    """
    A client for the openblockperf backend.

    This client handles the authentication with the backend and provides a
    simple interface to make requests to the backend.
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expiry: float = 0

    def _get_challenge(self) -> str:
        """Get a challenge from the server for authentication."""
        response = requests.get(
            f"{self.base_url}/auth/challenge",
            params={"client_id": self.client_id},
        )
        response.raise_for_status()
        return response.json()["challenge"]

    def _solve_challenge(self, challenge: str) -> str:
        """
        Solve the challenge using client secret.
        In a real implementation, this would implement the specific challenge-response algorithm.
        """
        # This is a simplified example - real implementation would depend on the API's requirements
        return f"{challenge}:{self.client_secret}"

    def _authenticate(self) -> None:
        """Perform the challenge-response authentication flow."""
        challenge = self._get_challenge()
        solution = self._solve_challenge(challenge)

        response = requests.post(
            f"{self.base_url}/auth/token",
            json={
                "client_id": self.client_id,
                "challenge": challenge,
                "solution": solution,
            },
        )
        response.raise_for_status()

        token_data = response.json()
        self._token = token_data["token"]
        self._token_expiry = time.time() + token_data.get("expires_in", 3600)

    def _ensure_valid_token(self) -> None:
        """Ensure we have a valid token, requesting a new one if needed."""
        if not self._token or time.time() >= self._token_expiry:
            self._authenticate()

    def _make_request(
        self, method: str, endpoint: str, **kwargs
    ) -> requests.Response:
        """Make an authenticated request to the API."""
        self._ensure_valid_token()

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"

        response = requests.request(
            method,
            f"{self.base_url}/{endpoint.lstrip('/')}",
            headers=headers,
            **kwargs,
        )

        if response.status_code == 401:
            # Token might be expired or invalid, retry once with new token
            self._token = None
            self._ensure_valid_token()
            headers["Authorization"] = f"Bearer {self._token}"
            response = requests.request(
                method,
                f"{self.base_url}/{endpoint.lstrip('/')}",
                headers=headers,
                **kwargs,
            )

        response.raise_for_status()
        return response

    def get(self, endpoint: str, **kwargs) -> Mapping[str, Any]:
        """Perform GET request to the API."""
        response = self._make_request("GET", endpoint, **kwargs)
        return response.json()

    def post(self, endpoint: str, **kwargs) -> Mapping[str, Any]:
        """Perform POST request to the API."""
        response = self._make_request("POST", endpoint, **kwargs)
        return response.json()

    # Add other HTTP methods as needed (put, delete, etc.)

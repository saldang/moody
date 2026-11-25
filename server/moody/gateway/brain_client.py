"""mTLS (+ optional OIDC client-credentials) client for the brain API."""

from __future__ import annotations

import ssl
import time

import httpx


class TokenProvider:
    """OAuth2 client-credentials against Keycloak; caches the token until shortly before expiry."""

    def __init__(self, token_url: str, client_id: str, client_secret: str, verify: ssl.SSLContext | bool = True):
        self.token_url, self.client_id, self.client_secret = token_url, client_id, client_secret
        self.verify = verify
        self._token = ""
        self._exp = 0.0

    async def token(self) -> str:
        if self._token and time.time() < self._exp - 30:
            return self._token
        async with httpx.AsyncClient(trust_env=False, timeout=10, verify=self.verify) as client:
            resp = await client.post(self.token_url, data={"grant_type": "client_credentials"},
                                     auth=(self.client_id, self.client_secret))
            resp.raise_for_status()
            data = resp.json()
        self._token = data["access_token"]
        self._exp = time.time() + float(data.get("expires_in", 60))
        return self._token


class BrainClient:
    def __init__(self, base_url: str, ssl_context: ssl.SSLContext | None,
                 tokens: TokenProvider | None = None, timeout: float = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self._http = httpx.AsyncClient(trust_env=False, verify=ssl_context or True, timeout=timeout)

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.tokens.token()}"} if self.tokens else {}

    async def turn(self, subject: str, session_id: str, text: str) -> dict:
        resp = await self._http.post(f"{self.base_url}/v1/turn", headers=await self._headers(),
                                     json={"subject": subject, "session_id": session_id, "text": text})
        resp.raise_for_status()
        return resp.json()

    async def notifications(self, subject: str) -> list[str]:
        resp = await self._http.get(f"{self.base_url}/v1/notifications", headers=await self._headers(),
                                    params={"subject": subject})
        resp.raise_for_status()
        return list(resp.json().get("items", []))

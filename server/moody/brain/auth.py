"""Optional OIDC bearer-token verification (Keycloak), on top of mTLS.

Open-source replacement for Entra ID service-to-service auth. When
``MOODY_OIDC_ISSUER`` is set every request must carry a valid access token,
issued by that realm, for the configured audience and an allowed client.
"""

from __future__ import annotations

import ssl

import jwt
from fastapi import HTTPException, Request


class OIDCVerifier:
    def __init__(self, issuer: str, audience: str, allowed_clients: set[str], jwks_url: str = "",
                 ssl_context: ssl.SSLContext | None = None) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.allowed_clients = allowed_clients
        self._jwks = jwt.PyJWKClient(jwks_url or f"{self.issuer}/protocol/openid-connect/certs",
                                     cache_keys=True, lifespan=600, ssl_context=ssl_context)

    def verify(self, token: str) -> dict:
        key = self._jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256", "ES256", "PS256"], audience=self.audience,
            issuer=self.issuer, options={"require": ["exp", "iat", "iss", "aud"]}, leeway=30,
        )
        client = claims.get("azp") or claims.get("client_id")
        if self.allowed_clients and client not in self.allowed_clients:
            raise jwt.InvalidTokenError("client not allowed")
        return claims


def make_dependency(verifier: OIDCVerifier | None):  # noqa: ANN201
    async def dependency(request: Request) -> dict | None:
        if verifier is None:
            return None
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        try:
            return verifier.verify(header[7:])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(401, "invalid token") from exc

    return dependency

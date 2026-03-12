"""Config flow for Shark IQ Robot Vacuums (HACS) — PKCE auth."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_USERNAME

from .const import (
    AUTH0_CLIENT_ID,
    AUTH0_REDIRECT_URI,
    AUTH0_SCOPES,
    AUTH0_URL,
    AYLA_LOGIN_URL,
    CONF_ACCESS_TOKEN,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    SHARK_APP_ID,
    SHARK_APP_SECRET,
)

_LOGGER = logging.getLogger(__name__)


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _build_authorize_url(code_challenge: str) -> str:
    """Build the Auth0 PKCE authorize URL."""
    params = {
        "response_type": "code",
        "client_id": AUTH0_CLIENT_ID,
        "redirect_uri": AUTH0_REDIRECT_URI,
        "scope": AUTH0_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH0_URL}/authorize?{urlencode(params)}"


class SharkIqConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shark IQ."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._code_verifier: str | None = None
        self._authorize_url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Show the Auth0 login URL and ask user to paste callback URL."""
        if user_input is None:
            # Generate PKCE pair and build URL
            self._code_verifier, code_challenge = _generate_pkce()
            self._authorize_url = _build_authorize_url(code_challenge)
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("callback_url"): str,
                    }
                ),
                description_placeholders={
                    "authorize_url": self._authorize_url,
                },
            )

        # User pasted the callback URL — extract the authorization code
        errors: dict[str, str] = {}
        callback_url = user_input["callback_url"].strip()

        try:
            parsed = urlparse(callback_url)
            qs = parse_qs(parsed.query)
            if not qs:
                # Some callbacks use fragment instead of query
                qs = parse_qs(parsed.fragment)
            code = qs.get("code", [None])[0]
        except Exception:
            code = None

        if not code:
            errors["callback_url"] = "no_code"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required("callback_url"): str}
                ),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        # Exchange code for Auth0 tokens
        try:
            auth0_tokens = await self._exchange_code(code)
        except Exception:
            _LOGGER.exception("Failed to exchange Auth0 code")
            errors["callback_url"] = "auth_failed"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required("callback_url"): str}
                ),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        # Exchange Auth0 id_token for Ayla token
        try:
            ayla_tokens = await self._exchange_ayla_token(auth0_tokens["id_token"])
        except Exception:
            _LOGGER.exception("Failed to exchange Ayla token")
            errors["callback_url"] = "auth_failed"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required("callback_url"): str}
                ),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        # Build config entry data
        data = {
            CONF_ACCESS_TOKEN: ayla_tokens["access_token"],
            CONF_REFRESH_TOKEN: ayla_tokens["refresh_token"],
            CONF_ID_TOKEN: auth0_tokens["id_token"],
            CONF_USERNAME: self._email_from_id_token(auth0_tokens["id_token"]),
        }

        unique_id = data[CONF_USERNAME]
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=f"Shark IQ ({unique_id})", data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth — same as user flow."""
        return await self.async_step_user()

    @staticmethod
    def _email_from_id_token(id_token: str) -> str:
        """Extract email from JWT id_token without verification."""
        try:
            payload = id_token.split(".")[1]
            # Add padding
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return claims.get("email", "shark_user")
        except Exception:
            return "shark_user"

    async def _exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for Auth0 tokens via PKCE."""
        token_url = f"{AUTH0_URL}/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": AUTH0_CLIENT_ID,
            "code_verifier": self._code_verifier,
            "code": code,
            "redirect_uri": AUTH0_REDIRECT_URI,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                _LOGGER.debug("Auth0 token exchange successful")
                return data

    async def _exchange_ayla_token(self, id_token: str) -> dict[str, Any]:
        """Exchange Auth0 id_token for Ayla Networks access/refresh tokens."""
        url = f"{AYLA_LOGIN_URL}/api/v1/token_sign_in"
        payload = {
            "app_id": SHARK_APP_ID,
            "app_secret": SHARK_APP_SECRET,
            "token": id_token,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                _LOGGER.debug("Ayla token exchange successful")
                return data

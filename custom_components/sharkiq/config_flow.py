"""Config flow for Shark IQ Robot Vacuums (HACS) — browser PKCE auth.

SharkNinja uses Cloudflare Turnstile + Auth0 bot detection, so server-side
auth doesn't work. User logs in via real browser, pastes the callback URL.
Tokens are persisted and auto-refreshed so this only happens once.
"""

from __future__ import annotations

import asyncio
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
        """Show PKCE authorize URL, user pastes callback URL after browser login."""
        errors: dict[str, str] = {}

        if user_input is None:
            self._code_verifier, code_challenge = _generate_pkce()
            params = {
                "response_type": "code",
                "client_id": AUTH0_CLIENT_ID,
                "redirect_uri": AUTH0_REDIRECT_URI,
                "scope": AUTH0_SCOPES,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
            self._authorize_url = f"{AUTH0_URL}/authorize?{urlencode(params)}"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                description_placeholders={
                    "authorize_url": self._authorize_url,
                },
            )

        callback_url = user_input["callback_url"].strip()
        code = self._extract_code(callback_url)

        if not code:
            errors["callback_url"] = "no_code"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        # Exchange PKCE code for Auth0 tokens
        auth0_tokens = None
        try:
            async with asyncio.timeout(15):
                auth0_tokens = await self._exchange_pkce_code(code)
        except TimeoutError:
            _LOGGER.error("Auth0 token exchange timed out")
            errors["callback_url"] = "auth_failed"
        except aiohttp.ClientResponseError as exc:
            _LOGGER.error("Auth0 token exchange HTTP %s: %s", exc.status, exc.message)
            errors["callback_url"] = "auth_failed"
        except Exception as exc:
            _LOGGER.exception("Auth0 token exchange failed: %s", exc)
            errors["callback_url"] = "auth_failed"

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        if "id_token" not in auth0_tokens:
            error_msg = auth0_tokens.get("error_description", auth0_tokens.get("error", "unknown"))
            _LOGGER.error("Auth0 did not return id_token: %s", error_msg)
            errors["callback_url"] = "auth_failed"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        # Exchange id_token for Ayla tokens
        try:
            async with asyncio.timeout(15):
                ayla_tokens = await self._exchange_ayla_token(auth0_tokens["id_token"])
        except Exception as exc:
            _LOGGER.exception("Ayla token exchange failed: %s", exc)
            errors["callback_url"] = "ayla_failed"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required("callback_url"): str}),
                description_placeholders={
                    "authorize_url": self._authorize_url or "",
                },
                errors=errors,
            )

        email = self._email_from_id_token(auth0_tokens["id_token"])
        data = {
            CONF_ACCESS_TOKEN: ayla_tokens["access_token"],
            CONF_REFRESH_TOKEN: ayla_tokens["refresh_token"],
            CONF_ID_TOKEN: auth0_tokens["id_token"],
            CONF_USERNAME: email,
        }

        await self.async_set_unique_id(email)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=f"Shark IQ ({email})", data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth."""
        return await self.async_step_user()

    @staticmethod
    def _extract_code(url: str) -> str | None:
        """Extract authorization code from a callback URL."""
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if not qs:
                qs = parse_qs(parsed.fragment)
            return qs.get("code", [None])[0]
        except Exception:
            return None

    @staticmethod
    def _email_from_id_token(id_token: str) -> str:
        """Extract email from JWT id_token without verification."""
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return claims.get("email", "shark_user")
        except Exception:
            return "shark_user"

    async def _exchange_pkce_code(self, code: str) -> dict[str, Any]:
        """Exchange PKCE authorization code for Auth0 tokens."""
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
                data = await resp.json()
                if resp.status >= 400:
                    error_msg = data.get("error_description", data.get("error", f"HTTP {resp.status}"))
                    _LOGGER.error("Auth0 token exchange error: %s", error_msg)
                return data

    async def _exchange_ayla_token(self, id_token: str) -> dict[str, Any]:
        """Exchange Auth0 id_token for Ayla access/refresh tokens."""
        url = f"{AYLA_LOGIN_URL}/api/v1/token_sign_in"
        payload = {
            "app_id": SHARK_APP_ID,
            "app_secret": SHARK_APP_SECRET,
            "token": id_token,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

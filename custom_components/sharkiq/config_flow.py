"""Config flow for Shark IQ Robot Vacuums (HACS) — browser-sim Auth0 + token persistence."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

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

BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Mobile Safari/537.36"
)


class SharkIqConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shark IQ."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — username/password form."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                async with asyncio.timeout(30):
                    auth0_tokens = await self._do_auth0_login(username, password)
            except AuthRateLimited:
                errors["base"] = "rate_limited"
            except AuthInvalid:
                errors["base"] = "invalid_auth"
            except TimeoutError:
                _LOGGER.error("Auth0 login timed out")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected auth error")
                errors["base"] = "unknown"

            if not errors:
                # Exchange Auth0 id_token for Ayla tokens
                try:
                    async with asyncio.timeout(15):
                        ayla_tokens = await self._exchange_ayla_token(
                            auth0_tokens["id_token"]
                        )
                except TimeoutError:
                    _LOGGER.error("Ayla token exchange timed out")
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Ayla token exchange failed")
                    errors["base"] = "cannot_connect"

            if not errors:
                data = {
                    CONF_ACCESS_TOKEN: ayla_tokens["access_token"],
                    CONF_REFRESH_TOKEN: ayla_tokens["refresh_token"],
                    CONF_ID_TOKEN: auth0_tokens["id_token"],
                    CONF_USERNAME: username,
                }

                await self.async_set_unique_id(username)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Shark IQ ({username})", data=data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth."""
        return await self.async_step_user()

    async def _do_auth0_login(
        self, username: str, password: str
    ) -> dict[str, Any]:
        """Perform Auth0 browser-sim login (3-step: authorize → /u/login → token exchange).

        This mimics what the SharkClean mobile app does, bypassing the
        IdP redirect that blocks normal browser PKCE flow.
        """
        headers = {
            "User-Agent": BROWSER_UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": AUTH0_URL,
            "Referer": AUTH0_URL + "/",
        }

        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            # Step 1: GET /authorize — follow redirects to get the state param
            authorize_url = (
                f"{AUTH0_URL}/authorize?"
                f"os=android&response_type=code&client_id={AUTH0_CLIENT_ID}"
                f"&redirect_uri={AUTH0_REDIRECT_URI}&scope={AUTH0_SCOPES}"
            )
            async with session.get(
                authorize_url, headers=headers, allow_redirects=True
            ) as resp:
                parsed = urlparse(str(resp.url))
                state = parse_qs(parsed.query).get("state", [None])[0]

            if not state:
                raise AuthInvalid("No state returned from /authorize")

            # Step 2: POST /u/login with credentials
            login_url = f"{AUTH0_URL}/u/login?state={state}"
            form_data = {
                "state": state,
                "username": username,
                "password": password,
                "action": "default",
            }
            async with session.post(
                login_url,
                headers=headers,
                data=form_data,
                allow_redirects=False,
            ) as resp:
                redirect_url = resp.headers.get("Location", "")

            # Extract authorization code from redirect chain
            code = None

            if redirect_url.startswith("/authorize/resume"):
                # Follow the resume redirect to get the final callback with code
                resume_url = AUTH0_URL + redirect_url
                async with session.get(
                    resume_url, headers=headers, allow_redirects=False
                ) as resp:
                    final_url = resp.headers.get("Location", "")
                    if final_url:
                        parsed = urlparse(final_url)
                        code = parse_qs(parsed.query).get("code", [None])[0]
            elif redirect_url.startswith(AUTH0_REDIRECT_URI):
                # Direct redirect to callback
                parsed = urlparse(redirect_url)
                code = parse_qs(parsed.query).get("code", [None])[0]

            if not code:
                # Check if it's a rate limit or bad credentials
                if "429" in redirect_url or "blocked" in redirect_url.lower():
                    raise AuthRateLimited("Login rate limited (429)")
                if redirect_url.startswith("/u/login"):
                    # Redirected back to login = bad credentials
                    raise AuthInvalid("Invalid username or password")
                raise AuthInvalid(f"Auth0 login failed, redirect: {redirect_url}")

            # Step 3: Exchange code for tokens
            token_url = f"{AUTH0_URL}/oauth/token"
            payload = {
                "grant_type": "authorization_code",
                "client_id": AUTH0_CLIENT_ID,
                "code": code,
                "redirect_uri": AUTH0_REDIRECT_URI,
            }
            async with session.post(
                token_url,
                headers={"Content-Type": "application/json"},
                json=payload,
            ) as resp:
                token_data = await resp.json()

            if "id_token" not in token_data:
                raise AuthInvalid(
                    f"Auth0 did not return id_token: {token_data.get('error_description', 'unknown')}"
                )

            return token_data

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


class AuthRateLimited(Exception):
    """Auth0 rate limited the login attempt."""


class AuthInvalid(Exception):
    """Invalid credentials."""

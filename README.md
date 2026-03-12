# Shark IQ Robot Vacuums — HACS Integration

Custom Home Assistant integration for Shark IQ robot vacuums using **PKCE OAuth2 authentication** instead of the broken password-based login.

## Why?

The built-in HA `sharkiq` integration uses password-based Auth0 login, which is blocked by SharkNinja's bot detection (429 errors). This integration uses the PKCE authorization code flow — you log in via your real browser, paste the callback URL, and tokens are persisted + auto-refreshed.

## Installation

### HACS (recommended)

1. Add this repo as a custom repository in HACS
2. Install "Shark IQ Robot Vacuums"
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services → Add Integration → "Shark IQ"

### Manual

Copy `custom_components/sharkiq/` to your HA `config/custom_components/` directory.

## Setup

1. The integration shows an Auth0 login URL
2. Open it in your browser, log in with your SharkNinja account
3. After login, your browser tries to open a `com.sharkninja.shark://` URL — this won't load, that's expected
4. Copy the full URL from the address bar and paste it into HA
5. Tokens are stored and auto-refreshed — you shouldn't need to re-authenticate unless tokens fully expire

## Features

- Start/Stop/Pause cleaning
- Return to dock
- Locate vacuum
- Fan speed control (Eco/Normal/Max)
- Battery level
- Vacuum state (cleaning, docked, paused, returning, idle)

## Credits

Built on the [sharkiq](https://github.com/JeffResc/sharkiq) Python library by @JeffResc.

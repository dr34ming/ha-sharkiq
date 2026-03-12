# Shark IQ Robot Vacuums — HACS Integration

Custom Home Assistant integration for Shark IQ robot vacuums with **working authentication**.

## Why?

The built-in HA `sharkiq` integration is broken — SharkNinja added Cloudflare Turnstile captcha and Auth0 bot detection that blocks all server-side login attempts (password grant, browser simulation, everything). You get 429 errors or "suspicious request requires verification."

This integration uses PKCE OAuth2 — you log in through your real browser (captcha and all), paste the callback URL back into HA, and tokens are persisted and auto-refreshed from then on. One-time setup, then it just works.

## Installation

### HACS (recommended)

1. Add this repo as a custom repository in HACS
2. Install "Shark IQ Robot Vacuums"
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services → Add Integration → "Shark IQ"

### Manual

Copy `custom_components/sharkiq/` to your HA `config/custom_components/` directory and restart.

## Setup

> SharkNinja's auth is hostile to automation. Their login page uses a mobile app deep link (`com.sharkninja.shark://`) as the OAuth redirect, which means desktop browsers can't capture it normally. You'll need browser DevTools open. This only needs to happen once — after setup, tokens auto-refresh indefinitely.

### Step-by-step

1. **Add the integration** in HA (Settings → Devices & Services → Add Integration → Shark IQ)

2. **Open Chrome DevTools** — press `F12` or `Cmd+Option+I`, go to the **Network** tab

3. **Copy the authorize URL** from the HA setup dialog and **paste it into Chrome's address bar**

4. **Log in** with your SharkClean account credentials. You may need to solve a captcha.

5. **After login**, Chrome will try to navigate to a `com.sharkninja.shark://` URL. This is a mobile app deep link — **it will show a gray screen, blank page, or "can't open" error.** That's expected.

6. **Find the redirect in DevTools Network tab:**
   - Look for the request to `login.sharkninja.com/authorize` with status **302**
   - Click on it, then look at **Response Headers**
   - Copy the `location` header value — it looks like:
     ```
     com.sharkninja.shark://login.sharkninja.com/ios/com.sharkninja.shark/callback?code=XXXXXXX
     ```

7. **Paste that URL** into the "Callback URL" field in HA and click Submit

8. **Be quick** — the authorization code expires in ~30 seconds. If you get "auth failed," start over from step 1.

### What if it expires?

Just start over — click Add Integration again. Each attempt generates a fresh PKCE challenge. If you're already logged into SharkNinja from a previous attempt, the authorize URL will auto-redirect (302) without needing to log in again, making it faster.

### After setup

Tokens are stored in the HA config entry and auto-refreshed. You should never need to re-authenticate unless you change your SharkNinja password or tokens fully expire (months of HA being offline).

## Features

- Start/Stop/Pause cleaning
- Return to dock
- Locate vacuum (chirp)
- Fan speed control (Eco/Normal/Max)
- Battery level
- Vacuum state (cleaning, docked, paused, returning, idle)
- Room-specific cleaning
- Error code/message reporting
- Low light mode detection
- Recharge-and-resume status

## Credits

Built on the [sharkiq](https://github.com/JeffResc/sharkiq) Python library by @JeffResc.

"""Constants for the Shark IQ integration."""

from datetime import timedelta

DOMAIN = "sharkiq"

UPDATE_INTERVAL = timedelta(seconds=30)
API_TIMEOUT = 20

# Auth0 / PKCE constants (from sharkiq library)
AUTH0_URL = "https://login.sharkninja.com"
AUTH0_CLIENT_ID = "wsguxrqm77mq4LtrTrwg8ZJUxmSrexGi"
AUTH0_SCOPES = "openid profile email offline_access"
AUTH0_REDIRECT_URI = (
    "com.sharkninja.shark://login.sharkninja.com/ios/com.sharkninja.shark/callback"
)

# Ayla Networks constants
AYLA_LOGIN_URL = "https://user-sharkue1.aylanetworks.com"
SHARK_APP_ID = "ios_shark_prod-3A-id"
SHARK_APP_SECRET = "ios_shark_prod-74tFWGNg34LQCmR0m45SsThqrqs"

# Config entry data keys
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ID_TOKEN = "id_token"

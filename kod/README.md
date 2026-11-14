# Source code

| Folder | What |
|---|---|
| [`app/`](app) | Android app (Kotlin + Jetpack Compose). Build: `./gradlew assembleDebug` |
| [`server/`](server) | Runs on the Raspberry Pi: Telegram bot, FastAPI for the app, ad video renderer, music player, label printer |

## Setup notes

- Keys and tokens are never in the code. The server reads them from `butiksbot.env` (see `butiksbot.env.exempel`).
- Weather location: set `VADER_LAT` and `VADER_LON` in `butiksbot.env`.
- The app finds the Pi on the local network by mDNS. For remote access, put your Pi's Tailscale address in
  `Anslutning.kt` (`TAILSCALE`).
- The API only answers on the local network and Tailscale, and every call needs a per-phone key.

Comments and identifiers are in Swedish.

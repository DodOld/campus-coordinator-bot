# Telegram proxy failover design

## Goal

Restore Telegram Bot API access from the current VPS through a user-supplied
encrypted proxy profile, without routing unrelated bot traffic through that
proxy. Allow later addition of independent proxy endpoints for bounded
failover.

## Stage 1: validate the supplied route

- Install the required Xray runtime from its official distribution.
- Store the user-supplied JSON outside the Git checkout with root-only
  permissions; never log or commit its endpoint, password, or keys.
- Run Xray as a systemd service exposing only its configured loopback SOCKS
  listener.
- Test `api.telegram.org` through that SOCKS listener. Do not change the bot
  while the route has not passed this test.
- If the test fails, stop and disable the service, preserving the original bot
  networking and reporting only a safe failure summary.

## Stage 2: bot integration

- Add optional `TELEGRAM_PROXY_URL` support to settings and create aiogram's
  HTTP session with that proxy only when it is configured.
- Keep the current direct path unchanged when the setting is absent.
- Configure the successful local SOCKS listener in server `.env`, without
  exposing credentials in logs or source control.
- Rebuild and restart only the bot service, then verify polling and a Telegram
  command.

## Stage 3: later failover

- Introduce an ordered, comma-separated `TELEGRAM_PROXY_URLS` setting only
  after at least two independently validated proxy profiles are supplied.
- On a Telegram network error, try the next endpoint with bounded exponential
  backoff; do not retry API-side authorization or validation failures.
- Health logs and Debug notifications identify endpoints only by an ordinal
  label, never by host, port, URL, or credential.

## Scope and safety

- The supplied profile is treated as secret configuration, not repository
  content.
- The Xray listener remains bound to loopback; no proxy port is published to
  the Internet.
- SSH, UFW, password authentication, and existing database configuration are
  not changed.

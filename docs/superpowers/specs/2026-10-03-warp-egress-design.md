# WARP egress design

## Goal

Restore the deployed Telegram bot's outbound access to Telegram Bot API from a
VPS where direct HTTPS connections to `api.telegram.org` time out, without
adding a third-party public proxy or changing Telegram credentials.

## Chosen approach

Install the official Cloudflare WARP client on the VPS, register its consumer
client profile, and enable full traffic-and-DNS tunnelling. This needs no bot
code change: Docker containers retain their normal networking while the host
routes outbound traffic through WARP.

## Validation

1. Keep the existing SSH session open while enabling WARP.
2. Verify that HTTPS to `api.telegram.org` succeeds from the host and from the
   bot container without printing the bot token.
3. Restart only the bot container and confirm polling starts and the health
   endpoint stays healthy.
4. Check that the bot and database remain within the available memory budget.

## Failure handling

If WARP cannot connect or Telegram remains unreachable, immediately disconnect
the client and leave the bot configuration unchanged. Do not add an arbitrary
Telegram IP mapping or a public proxy. The WARP package may remain installed,
but no traffic must stay routed through it after a failed validation.

## Scope

- The change affects outbound routing for the VPS; it does not add SSH keys,
  change SSH password access, alter UFW rules, or expose a new inbound port.
- Because the VPS has 709 MiB RAM, WARP is accepted only if the bot remains
  healthy without memory pressure or OOM events.

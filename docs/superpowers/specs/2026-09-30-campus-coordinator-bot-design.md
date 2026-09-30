# Campus Coordinator Bot: design

## Purpose and scope

`campus-coordinator-bot` is an async Python 3.12+ Telegram bot for explicitly
allowed supergroups. It supports forum topics, sends technical output only to
dedicated topics, performs a controlled `!all` notification, monitors public
VK communities through the official VK API, and provides a future-facing
iCalendar boundary. The bot never responds to private chats.

The first version deliberately does not integrate with the existing Go
schedule system and does not scrape VK or use user credentials.

## Architecture

The new `app` package has isolated layers:

- aiogram handlers validate incoming Telegram messages and delegate work;
- services own `!all`, chat policy, Debug reporting, and VK orchestration;
- SQLAlchemy repositories persist state behind focused interfaces;
- an async VK API client and periodic poller implement resilient delivery;
- the schedule package contains protocols and iCalendar implementation only;
- application startup owns configuration, database lifecycle, polling,
  background tasks, structured logging, and a small health endpoint.

Docker Compose runs the bot and PostgreSQL. Alembic owns the database schema.
The bot uses long polling for local/initial deployment and shuts down cleanly:
new work stops, tasks are cancelled after a bounded grace period, and HTTP and
database sessions close.

## Configuration and topic policy

All runtime configuration is loaded from a non-committed `.env`. The repository
contains an `.env.example` with no credentials or real IDs. Configuration
includes Telegram and VK tokens, `DATABASE_URL`, allowed chat IDs, a per-chat
mapping of `debug`, `posts`, and `schedule` thread IDs, and
`MEMBER_IDS_JSON`.

`MEMBER_IDS_JSON` is the operator-provided JSON list of candidate Telegram user
IDs for `!all`. It is never logged. It is the only membership source because
the official Bot API cannot enumerate all group members. Each candidate's
current status is fetched with `getChatMember`; bots, left/kicked users, and
deleted accounts are excluded before sending.

For a forum chat, the bot may send messages only to the configured `debug`,
`posts`, and `schedule` topic IDs. Every error, background-task result, and
configuration change goes to `debug`. VK sources may target only `posts` or
`schedule`; a target outside that allowlist is rejected. `schedule` is reserved
in this release and is not populated by the schedule module.

For a non-forum group, each configured topic value may be null. `debug: null`
means send technical output in the chat root. If Debug delivery cannot be
configured, the bot logs the event to structured stdout only. The README makes
this fallback explicit.

Private chats and chats outside the allowlist are dropped by the earliest
possible handler filter, without a reply or Debug message.

## `!all`

`!all` is accepted in any topic of an allowed group. It does not write back to
the invoking topic. The handler stores the original chat, topic, message, actor,
requested text, and final recipient count in its audit record.

After recipient validation, the bot sends escaped `text_mention` entities in
safe, bounded batches to the group's Debug topic. Once all mention batches are
sent, it sends a separate HTML-formatted message:

```
Вас упомянули в «ссылка»
```

Only `ссылка` is clickable. It targets the original group message using its
canonical Telegram message link. The bot does not forward the message and does
not expose a raw URL. If a safe usable link cannot be built (including content
protection), the command records the failure and sends a neutral Debug error
without revealing protected content or secrets.

Telegram message length and rate limits are respected by deterministic
batching and bounded inter-batch sends. The audit is committed transactionally
with an idempotency key derived from the incoming update/message.

## VK administration and monitoring

Only Telegram administrators of an allowed group may administer VK sources,
and only from its Debug topic:

- `!vk add <community> <topic_id> [preview]` validates a public community via
  the official VK API and creates/enables a source;
- `!vk list` reports the group's configured sources in Debug;
- `!vk remove <id>` disables the selected source.

The source stores the group chat, VK `owner_id`, title, canonical URL, target
topic, enabled state, polling interval, preview setting, and check state.
The periodic worker uses the documented `wall.get` API only. New posts are
registered with a database uniqueness constraint over `(source_id, post_id)`
before delivery, so a restart cannot republish a delivered post. The default
notification contains a title, a short escaped text excerpt, and the original
VK link; it never copies media or full text. Preview is opt-in per source.

The client honours VK API throttling and retry hints, retries transient network
and service failures with capped exponential backoff and jitter, and emits
sanitized Debug errors after final failure. Tokens, passwords, authorization
headers, and full secret values are never included in logs or Telegram output.

For communities controlled by the administrators, the README documents an
optional future VK Community Long Poll/Callback mode and its ownership and
verification requirements. It is not presented as a way to instantly monitor
third-party public communities.

## Schedule boundary

`ScheduleProvider` supplies normalized events and date-based queries.
`ICalendarScheduleProvider` loads an `.ics` document from a URL or file,
normalizes time zones, expands recurring events, and produces today/tomorrow
views. It has no Telegram output or connection to the Go system.

A precise TODO records the contract that a future contributor needs before
integrating the Go replacement: authentication method, service endpoints or
event schema, external identifiers, timezone policy, recurrence/exception and
cancellation semantics, pagination/synchronization mechanism, idempotency
contract, error taxonomy, rate limits, and SLA.

## Persistence and operations

The initial Alembic migration creates:

- `chat_settings` for allowed chat and topic policy;
- `processed_updates` keyed by Telegram update ID;
- `all_command_audit` for `!all` provenance and delivery outcome;
- `vk_sources` for monitor configuration;
- `vk_processed_posts` with unique source/post identity;
- optional delivery/job state needed to make retries idempotent.

Incoming updates are claimed once by `update_id`; duplicate deliveries have no
observable side effect. Health reports process readiness and database
connectivity without configuration or credential values. JSON structured logs
include correlation IDs and sanitized error class/context.

## Verification

Automated tests cover mention entity batching and exclusions, duplicate VK
post suppression across simulated restart, and VK/Telegram API error handling
including sanitized Debug reports. They also cover private-chat filtering and
topic-policy validation where practical. CI/local commands run formatting,
type checks when configured, migrations, and pytest.

The README covers BotFather token setup, `.env`, Docker Compose startup, DB
migration, making the bot an administrator with the least required rights,
creating and recording Debug/Posts/Schedule topics, `!all` membership and
message-link limitations, VK tokens and source commands, protected-content
behaviour, and the non-forum fallback.

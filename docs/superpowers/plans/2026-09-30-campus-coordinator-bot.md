# Campus Coordinator Bot implementation plan

## Boundaries

Implement only the bot described in the approved design. All product code is
new because the repository contains no existing application code. Work on
`main`; when verification is complete, fast-forward `master` to the completed
`main` commit as requested.

## Work sequence

1. Bootstrap Python 3.12 project metadata, locked production/test dependencies,
   package layout, lint/type/test configuration, `.gitignore`, `.env.example`,
   Dockerfile, and Compose PostgreSQL health checks.
2. Add typed Pydantic settings with secret-safe validation and topic policy;
   configure JSON structured logging with explicit secret redaction.
3. Implement SQLAlchemy async engine/session, declarative models and focused
   repositories. Add Alembic configuration and initial migration for chat
   policy, processed updates, `!all` audit, VK sources, and deduplicated posts.
4. Implement Telegram utilities: early private/unapproved-chat gate,
   administrator guard, message-link construction, safe HTML escaping,
   `text_mention` batching, Debug delivery, and idempotent update claim.
5. Implement the `!all` handler so it validates configured candidate IDs,
   excludes ineligible members, posts mention batches then the formatted
   `Вас упомянули в «ссылка»` message in Debug, and persists audit state.
6. Implement VK API client with response validation, rate-limit-aware retries,
   URL resolution, and no token logging. Add VK source administration commands
   restricted to group admins and Debug topic.
7. Implement periodic VK polling and idempotent source/post delivery to
   allowed Posts/Schedule targets, with sanitized Debug failures.
8. Implement `ScheduleProvider` and `ICalendarScheduleProvider` for file/URL
   input, timezone normalization, recurrence expansion, today/tomorrow queries,
   and an explicit integration-contract TODO.
9. Wire lifespan startup/shutdown, polling, jobs, aiohttp `/healthz`, and a
   runnable module entry point.
10. Write pytest coverage for mention batching, `!all` exclusion/order,
    duplicate VK records, retry/error sanitization, private-chat filtering, and
    schedule basics. Run the full suite and static checks. Document deployment,
    configuration, permissions, topic routing, operational limitations, and
    VK ownership caveats in README.

## Key technical decisions

- Use PostgreSQL conflict-safe inserts / unique constraints rather than in-memory
  locks for delivery idempotency.
- Use `MessageEntity(type="text_mention")` instead of unescaped `tg://user`
  markup for participant mentions.
- Use only official Bot API and VK API endpoints through `aiohttp`.
- Treat message-link construction and Debug reporting as fallible operations;
  the error path itself must not log or send secrets.
- Store target IDs, source configuration, audit, and completion state in the
  database. Environment variables bootstrap chat/topic policy and roster.

## Verification commands

```sh
cp .env.example .env
docker compose up --build
docker compose exec bot alembic upgrade head
uv run pytest
uv run ruff check .
```

The exact local command runner is finalized with the selected packaging tool;
Compose remains the production-like supported path.

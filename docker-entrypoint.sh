#!/bin/sh
set -eu
alembic upgrade head
exec campus-coordinator-bot

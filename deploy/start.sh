#!/bin/sh
set -eu

port="${PORT:-8000}"
max_attempts="${DATABASE_STARTUP_MAX_ATTEMPTS:-10}"
retry_seconds="${DATABASE_STARTUP_RETRY_SECONDS:-3}"

case "$port" in
  ''|*[!0-9]*)
    echo "PORT must be a number." >&2
    exit 1
    ;;
esac

attempt=1
until python manage.py migrate --noinput; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "Database migration failed after ${attempt} attempts." >&2
    exit 1
  fi

  echo "Database is not ready; retrying in ${retry_seconds}s (${attempt}/${max_attempts})." >&2
  attempt=$((attempt + 1))
  sleep "$retry_seconds"
done

python manage.py collectstatic --noinput --clear

exec gunicorn travel_api.wsgi:application \
  --bind "0.0.0.0:${port}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -

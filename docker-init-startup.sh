#!/bin/sh

# Extract host and port from DATABASE_URL
DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\).*/\1/p')
DB_PORT=$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
DB_PORT=${DB_PORT:-5432}  # Default to 5432 if not specified

# Wait for PostgreSQL
/usr/local/bin/wait-for-it ${DB_HOST}:${DB_PORT} --timeout=10 -- echo "PostgreSQL is up"

# Run migrations
cd /app && alembic upgrade head

# Execute the main command (which will be our Python application)
exec "$@"
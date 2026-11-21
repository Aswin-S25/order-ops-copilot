#!/usr/bin/env bash
# Runs ONCE, only when the Postgres data volume is empty.
# Creates the application roles (ADR-0003) and the dev + test databases.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$APP_OWNER_PASSWORD" -v user_pw="$APP_USER_PASSWORD" <<'SQL'
-- Owns the schema. Used only by migrations.
CREATE ROLE app_owner LOGIN PASSWORD :'owner_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- Runtime role for the API and workers. Owns nothing and cannot bypass RLS.
CREATE ROLE app_user LOGIN PASSWORD :'user_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
SQL

for db in orderops orderops_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -c "CREATE DATABASE ${db} OWNER app_owner"

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" -v db="$db" <<'SQL'
-- Nobody may connect unless explicitly granted.
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO app_owner, app_user;

-- Creating extensions needs superuser, so do it here rather than in migrations.
CREATE EXTENSION IF NOT EXISTS vector;

-- app_owner owns the schema; app_user may only use objects in it.
ALTER SCHEMA public OWNER TO app_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_user;

-- Tables and sequences that app_owner creates IN THE FUTURE are granted to app_user automatically.
-- Deliberately excluded: TRUNCATE, REFERENCES, TRIGGER.
-- Append-only audit tables will REVOKE UPDATE, DELETE in their own migration.
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_user;
SQL
done

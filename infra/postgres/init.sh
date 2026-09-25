#!/bin/sh
# Creates the three database roles used by the platform (ADR-002). Runs once, on first start.
#   app_owner    owns the schema, runs migrations (RLS does not apply to the table owner)
#   app_user     runtime role for API + workers — NO BYPASSRLS, so RLS policies are enforced
#   app_platform audited super-admin cross-tenant path — BYPASSRLS
# Default privileges are also set in template1 so test databases (created by pytest) inherit them.
set -eu
OWNER_PW="${APP_OWNER_PASSWORD:-app_owner}"
USER_PW="${APP_USER_PASSWORD:-app_user}"
PLATFORM_PW="${APP_PLATFORM_PASSWORD:-app_platform}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE app_owner LOGIN PASSWORD '${OWNER_PW}' CREATEDB;
CREATE ROLE app_user LOGIN PASSWORD '${USER_PW}' NOBYPASSRLS;
CREATE ROLE app_platform LOGIN PASSWORD '${PLATFORM_PW}' BYPASSRLS;
GRANT app_user TO app_owner;
ALTER DATABASE "${POSTGRES_DB}" OWNER TO app_owner;
SQL

for db in "$POSTGRES_DB" template1; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS citext;
ALTER SCHEMA public OWNER TO app_owner;
GRANT USAGE ON SCHEMA public TO app_user, app_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user, app_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_user, app_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO app_user, app_platform;
SQL
done

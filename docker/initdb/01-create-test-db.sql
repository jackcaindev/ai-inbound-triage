-- Postgres only runs POSTGRES_DB automatically; the test database used by
-- backend/tests/conftest.py needs to be created explicitly. This only runs once,
-- on first container init against a fresh volume.
CREATE DATABASE triage_test;

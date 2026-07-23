SELECT 'CREATE DATABASE sigra_integration'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'sigra_integration'
)\gexec

SELECT 'CREATE DATABASE sigra_migration_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'sigra_migration_test'
)\gexec

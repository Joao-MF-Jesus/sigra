-- FUTURE NEW DATABASE ONLY. Run after the existing Alembic chain, never at boot.
-- This is NOT a migration chain or a command to execute on homologation.
\set ON_ERROR_STOP on
BEGIN;
DO $$
DECLARE t text; n bigint;
BEGIN
  IF current_database() <> 'sigra_tcc_research' OR current_user <> 'sigra_research_owner'
     OR (SELECT array_agg(version_num) FROM public.alembic_version) IS DISTINCT FROM ARRAY['20261007_0015']::varchar[] THEN
    RAISE EXCEPTION 'NEW_RESEARCH_DATABASE_OWNER_REVISION_REQUIRED';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_class WHERE relforcerowsecurity AND relnamespace='public'::regnamespace) THEN
    RAISE EXCEPTION 'ALREADY_HARDENED_INSPECT_DO_NOT_REPLAY';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='sigra_research_runtime' AND rolcanlogin
      AND NOT (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication))
      OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='sigra_research_runtime')) THEN
    RAISE EXCEPTION 'UNPRIVILEGED_RUNTIME_WITHOUT_MEMBERSHIPS_REQUIRED';
  END IF;
  FOREACH t IN ARRAY ARRAY['users','auth_sessions','participant_test_runs','participant_study_sessions',
      'participant_questionnaires','expenses','maintenances','user_vehicles','vehicle_reports','fuel_consumption_reports'] LOOP
    IF EXISTS(SELECT FROM pg_class WHERE oid=to_regclass(format('public.%I',t))) THEN
      EXECUTE format('SELECT count(*) FROM public.%I',t) INTO STRICT n;
      IF n <> 0 THEN RAISE EXCEPTION 'NEW_RESEARCH_PRIVATE_TABLE_NOT_EMPTY'; END IF;
    END IF;
  END LOOP;
END $$;
REVOKE ALL ON DATABASE sigra_tcc_research FROM PUBLIC, sigra_research_runtime;
GRANT CONNECT ON DATABASE sigra_tcc_research TO sigra_research_owner, sigra_research_runtime;
DO $$
DECLARE s text; p text; t text;
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname IN ('public','academic','bronze','silver','gold','meta') LOOP
    FOR p IN SELECT 'PUBLIC' UNION SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
      EXECUTE format('REVOKE ALL ON SCHEMA %I FROM %s',s,CASE WHEN p='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(p) END);
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %s',s,CASE WHEN p='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(p) END);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %s',s,CASE WHEN p='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(p) END);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM %s',s,CASE WHEN p='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(p) END);
    END LOOP;
    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM sigra_research_runtime',s);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['users','auth_sessions','participant_test_runs','participant_study_sessions',
      'participant_questionnaires','expenses','maintenances','user_vehicles','vehicle_reports','fuel_consumption_reports'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY research_trusted_backend ON public.%I TO sigra_research_runtime USING (true) WITH CHECK (true)',t);
    EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO sigra_research_runtime',t);
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA public,academic TO sigra_research_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA academic TO sigra_research_runtime;
GRANT SELECT ON public.alembic_version,public.vehicles,public.motorcycles TO sigra_research_runtime;
GRANT USAGE,SELECT ON SEQUENCE public.users_id_seq,public.expenses_id_seq,public.maintenances_id_seq,
  public.user_vehicles_id_seq,public.vehicle_reports_id_seq,public.fuel_consumption_reports_id_seq TO sigra_research_runtime;
COMMIT;

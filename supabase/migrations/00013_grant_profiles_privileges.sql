-- 00002_create_profiles.sql set up RLS policies on `profiles` but never
-- granted base table privileges to authenticated/service_role. Without a
-- GRANT, Postgres denies access before RLS is even evaluated (confirmed via
-- `\dp profiles` showing anon/authenticated/service_role only had D/x/t,
-- missing SELECT/INSERT/UPDATE) — RLS then does the actual narrowing to
-- `user_id = auth.uid()`.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE profiles TO service_role;

create extension if not exists pg_cron;

select cron.schedule(
  'cleanup-login-attempts-daily',
  '0 3 * * *',
  $$delete from login_attempts
    where last_attempt_at < now() - interval '24 hours'
      and (locked_until is null or locked_until < now());$$
);

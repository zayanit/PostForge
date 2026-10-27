# Quickstart: Image Generation

Setup (migration, backend role grants, worker, Windows commands) is in
[`docs/generations.md`](../../docs/generations.md). Recorded results are in
[`docs/generation-verification.md`](../../docs/generation-verification.md).

## Automated checks (no credentials, no paid calls)

From the repository root:

```bash
backend/.venv/bin/python -m pytest -q backend/tests/unit backend/tests/contract \
  backend/tests/integration/test_generation_queue.py
cd frontend
npm run lint
npx tsc --noEmit
npx playwright test --config playwright.generations.config.ts
```

`test_generation_queue.py` starts a disposable PostgreSQL through `embedded-postgres` and applies the real `00019` migration.

## Manual validation (local Supabase and a disposable OpenAI key)

1. Apply migrations and start the API, worker, and frontend (`make dev` starts all three).
2. Sign in, create a brand, and add an OpenAI key in **Manage provider keys**.
3. With no Brand Kit answers, open **Generate an image**, choose a preset, submit, and confirm `Queued` → `Processing` → `Ready`.
4. Download the PNG and confirm its pixel dimensions match the preset exactly. Repeat for one wide preset (LinkedIn Banner) and one tall one (Instagram Story) and confirm the subject is not cut off.
5. Complete the Brand Kit, generate again, and confirm the result reflects it.
6. Deactivate the key, submit, and confirm `OPENAI_KEY_REQUIRED` with a link to provider settings.
7. Submit, close the tab, reopen **Image history**, and confirm the job finishes there.
8. Stop the worker while a job is processing, restart it, wait five minutes, and confirm the job ends as succeeded (if the image was stored) or `GENERATION_INTERRUPTED`, with no second OpenAI request in the OpenAI dashboard.
9. Wait more than five minutes on a result, then download; confirm a fresh link is used.
10. As a second user, request the first user's brand history and a generation ID; confirm generic not-found responses.
11. Delete a generation; confirm the object is gone from the `generation-assets` bucket and the row is gone.
12. Delete the brand; confirm its `brands/{id}/generations/` prefix is empty.

## Container validation

```bash
make build && make up
docker exec postforge sh -c "kill -STOP \$(pgrep -f '[a]pp.worker')"   # stall the worker
# within about 90 seconds the container reports unhealthy
docker exec postforge sh -c "kill -CONT \$(pgrep -f '[a]pp.worker')"
```

Stop Supabase while the container is idle and confirm the container stays healthy. Stop the container during a generation and confirm the job finishes before exit (`docker stop` honors the 300-second stop timeout set by `make up`).

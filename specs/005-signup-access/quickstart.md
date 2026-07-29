# Quickstart: Accessible Sign-up Flow

1. Start local Supabase and ensure the frontend environment variables are configured.
2. Start the backend with `set -a; source backend/.env; set +a; make dev-backend`.
3. In another terminal, run `make dev-frontend`.
4. Open `http://localhost:3000/login`.
5. Activate **Sign up** and confirm the URL is `/signup`.
6. Confirm the signup page's **Sign in** link returns to `/login`.
7. Run automated checks:

   ```bash
   cd frontend
   npm run lint
   npx playwright test tests/e2e/signup-flow.spec.ts
   npm run build
   ```

Verification results: `npm run lint` passed; `npx playwright test tests/e2e/signup-flow.spec.ts` failed because `127.0.0.1:3000` was unavailable; `npm run build` passed.

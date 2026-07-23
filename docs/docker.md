# Docker Deployment

This runbook builds and runs the PostForge frontend and backend as one `linux/amd64`
container. Run every local command from the repository root.

## Prerequisites

- Docker with the BuildKit builder running.
- A reachable Supabase project and its project URL, publishable key, secret key, JWT
  secret, and PostgreSQL connection string.
- For Bunny deployment, an image repository in Docker Hub or GitHub Container Registry
  and access to the [bunny.net dashboard](https://dash.bunny.net/).

## Build

Build the deployment architecture explicitly, including on Apple Silicon:

```bash
docker build --platform linux/amd64 -t postforge:local .
```

The command completes with output ending in an exported image and
`naming to docker.io/library/postforge:local`. Confirm the image exists and targets the
required platform:

```bash
docker image inspect postforge:local \
  --format 'image={{.RepoTags}} platform={{.Os}}/{{.Architecture}}'
```

Expected:

```text
image=[postforge:local] platform=linux/amd64
```

## Run Locally

Create a local runtime file named `.env.docker` with real values. This file is ignored by
Git and Docker; do not commit it.

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=replace-with-secret-key
SUPABASE_JWT_SECRET=replace-with-jwt-secret
DATABASE_URL=postgresql://user:password@host:5432/database
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=replace-with-publishable-key
NEXT_PUBLIC_API_URL=/api
NEXT_SERVER_API_URL=http://127.0.0.1:8000
```

Restrict the file to your user, then start the container:

```bash
chmod 600 .env.docker

docker run -d --name postforge --platform linux/amd64 \
  --env-file .env.docker \
  -p 3000:3000 \
  postforge:local
```

Open `http://localhost:3000`. Only container port 3000 is published; the backend remains
private on `127.0.0.1:8000` inside the container and is reached through the same-origin
`/api` proxy.

Wait up to 60 seconds for a healthy result:

```bash
deadline=$(( $(date +%s) + 60 ))
status="starting"
while [ "$(date +%s)" -lt "$deadline" ]; do
  status=$(docker inspect --format '{{.State.Health.Status}}' postforge)
  [ "$status" = "healthy" ] && break
  sleep 2
done
[ "$status" = "healthy" ] && echo "PostForge is healthy" || echo "PostForge is $status"
```

Stop and remove the container when finished:

```bash
docker stop postforge
docker rm postforge
```

## Configuration & Secrets

All configuration is supplied when the container starts. The Dockerfile contains no
application credentials or deployment-specific defaults (FR-005). `NEXT_PUBLIC_*`
values are intentionally sent to the browser and must never contain a secret; all other
credentials remain server-side.

| Variable | Consumer | Required value |
|---|---|---|
| `SUPABASE_URL` | Backend | Supabase API URL reachable from inside the container |
| `SUPABASE_SECRET_KEY` | Backend | Supabase secret/service-role credential; keep secret |
| `SUPABASE_JWT_SECRET` | Backend | JWT verification secret; keep secret |
| `DATABASE_URL` | Backend | PostgreSQL connection string reachable from inside the container; keep credentials secret |
| `NEXT_PUBLIC_SUPABASE_URL` | Browser | Supabase API URL reachable from each user's browser |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Browser | Supabase publishable key; public by design |
| `NEXT_PUBLIC_API_URL` | Browser | `/api` for same-origin backend access through Next.js |
| `NEXT_SERVER_API_URL` | Next.js server | `http://127.0.0.1:8000` for the private in-container backend |

For hosted Supabase, `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL` are normally the same
public HTTPS URL. For local Supabase on Docker Desktop, the backend needs a host address
such as `http://host.docker.internal:54321`, while the browser needs
`http://localhost:54321`. On Linux, add
`--add-host=host.docker.internal:host-gateway` to `docker run` when using that hostname.

Rotate a leaked credential at its source, update `.env.docker` or the hosting platform's
runtime variables, and replace the running container. Rebuilding the image is neither
required nor an acceptable way to distribute secrets.

## Healthcheck & Restart Behavior

Docker reports the container healthy only when both local processes return `2xx`:

- Backend: `http://127.0.0.1:8000/health`
- Frontend: `http://127.0.0.1:3000/login`

The checks use two-second request limits, reject redirects, run every 10 seconds, allow a
30-second start period, and mark the container unhealthy after three consecutive
failures. They do not call Supabase or perform a login. Healthy therefore means only that
both in-container processes are serving requests; it does not prove external-service
reachability. See the exact [healthcheck contract](../specs/002-dockerization/contracts/healthcheck.md).

Inspect current health and recent probe results:

```bash
docker inspect --format '{{.State.Health.Status}}' postforge
docker inspect --format '{{json .State.Health.Log}}' postforge
```

The entrypoint supervises `uvicorn` and `next start`. If either exits unexpectedly, it
restarts only that process with a new PID; the other process and the container remain
running. `tini` forwards stop signals, and the entrypoint waits for both children during
intentional shutdown. See the exact
[entrypoint contract](../specs/002-dockerization/contracts/entrypoint.md).

## Deploy to Bunny Magic Container

Bunny pulls an existing `linux/amd64` image from Docker Hub or GitHub Container Registry;
it does not build this repository. Publish an immutable version tag rather than `latest`:

```bash
docker tag postforge:local ghcr.io/YOUR_GITHUB_OWNER/postforge:VERSION
docker login ghcr.io
docker push ghcr.io/YOUR_GITHUB_OWNER/postforge:VERSION
```

Replace `YOUR_GITHUB_OWNER` and `VERSION` before running the commands. The same flow works
with a Docker Hub repository by changing the image name and registry login.

Deploy through Bunny's current Quick Deploy flow:

1. If the image is private, open **Magic Containers > Image Registries**, select
   **Add Image Registry**, choose GitHub or Docker, and add a read-only registry token.
   Public Docker Hub and GitHub registries require no added credentials.
2. Open **Add > App** or **Magic Containers > Deploy**, then choose **Quick Deploy**.
3. Select `ghcr.io/YOUR_GITHUB_OWNER/postforge:VERSION`. Verify the selected tag is the
   immutable version just pushed and the image architecture is `linux/amd64`.
4. Create a new app and add exactly one **CDN** endpoint for container port `3000`.
   Leave origin SSL disabled because Next.js serves plain HTTP inside the container. Do
   not create an endpoint for port 8000.
5. Leave persistent volumes empty; PostForge is stateless and stores application data in
   external Supabase.
6. Add all eight variables from **Configuration & Secrets** under **Environment
   Variables**. Use production Supabase and database values. Keep
   `NEXT_PUBLIC_API_URL=/api` and
   `NEXT_SERVER_API_URL=http://127.0.0.1:8000`. Environment variables are runtime
   configuration, not image build arguments.
7. Select the desired region, click **Deploy**, and monitor the app overview until
   provisioning completes.
8. Open the generated CDN endpoint and confirm `/login` loads. Sign in and verify the
   profile page before directing production traffic to the deployment.

For dashboard changes after deployment, use **Container Settings > Edit > Environment
Variables**, update the values, and select **Update Container** so replacement instances
receive them. Refer to Bunny's official
[Quick Deploy](https://docs.bunny.net/magic-containers/quick-deploy),
[image registry](https://docs.bunny.net/magic-containers/image-registries),
[environment variable](https://docs.bunny.net/magic-containers/environment-variables),
and [endpoint](https://docs.bunny.net/magic-containers/endpoints) documentation if the
dashboard labels change.

## Troubleshooting

### Container stays unhealthy

Inspect health results and process logs:

```bash
docker inspect --format '{{json .State.Health.Log}}' postforge
docker logs --tail 200 postforge
```

A missing required variable usually makes the backend crash-loop or makes the frontend
return a non-2xx response. Confirm every name in **Configuration & Secrets** is present,
then replace the container. Do not print secret values into shared logs or tickets. If
both local probes pass but sign-in fails, check Supabase and database connectivity
separately; external services are deliberately outside the container healthcheck.

### Port 3000 is already allocated

Stop the conflicting container shown by `docker ps`, or use a different host port while
keeping container port 3000 unchanged:

```bash
docker run -d --name postforge --platform linux/amd64 \
  --env-file .env.docker \
  -p 3001:3000 \
  postforge:local
```

Then browse to `http://localhost:3001`. Update local Supabase redirect URLs if its auth
configuration restricts redirects to port 3000.

### A rebuild appears stale

Confirm the expected source checkout and force all project layers to rebuild:

```bash
git status --short
docker build --no-cache --platform linux/amd64 -t postforge:local .
```

For Bunny, push a new immutable version tag and select that exact tag in the container
settings. Reusing an old tag can leave a previously resolved image digest deployed.

### Bunny cannot pull or start the image

- Confirm the registry token has read access and has not expired.
- Confirm the pushed image is `linux/amd64`; Magic Containers supports that architecture.
- Confirm the CDN endpoint targets only container port 3000.
- Confirm all eight runtime variables are configured on the container template.
- Review the Magic Containers app overview and container logs for image-pull or startup
  errors before redeploying.

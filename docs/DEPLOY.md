# Deploying AgriScout

The app is two pieces and they deploy to two places:

```
Browser ──► Vercel (React app, static files) ──── https calls ───► API container (FastAPI + analysis + PDF rendering)
```

**Why the API cannot run on Vercel.** The backend imports PyTorch (the CPU build is still well over a gigabyte, far past Vercel's function size limit), renders reports with headless Chromium, writes a SQLite database and image files to disk, and runs analyses as background jobs that outlive a request. Serverless functions fit none of that. So the **frontend goes on Vercel** and the **API runs in a container** on any host that can run Docker.

Do the API first, because the frontend needs its URL.

## 1. Deploy the API

### Build and test locally

```bash
docker build -t agriscout-api .
docker run --rm -p 8000:8000 \
  -e AGRISCOUT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  -e AGRISCOUT_ADMIN_KEY="choose-a-long-random-key" \
  -e AGRISCOUT_CORS_ORIGINS="http://localhost:5173" \
  agriscout-api
curl http://localhost:8000/api/health        # {"ok":true}
```

The first build downloads several GB (CPU PyTorch, Chromium) and takes a while. The image bakes in the demo: the real rice imagery from `deploy/demo-data/`, each farm's earlier survey already analysed, and a seeded database with reports. It needs no outbound access to start.

### Host it

Any host that runs a Docker image from a repository or registry will do (Render, Railway, Fly.io, a VM with Docker, and similar). What matters:

- **RAM: 2 GB or more.** PyTorch plus an analysis does not fit in 512 MB. Pick a plan accordingly.
- **Port:** the container listens on `$PORT` (default 8000). Hosts that set `PORT` need no extra config.
- **Health check path:** `/api/health`.
- **HTTPS:** the public URL must be `https://`, or the browser will block calls from the Vercel site (mixed content).
- **Persistence:** the SQLite database and generated files live on the container's disk and **reset on every restart or redeploy** back to the baked-in demo. That is fine for a demo. To keep data across restarts, mount a persistent volume at `/app/data`; on first start with an empty volume the container rebuilds the demo into it (about a minute), and your changes then persist.
- **Idle instances.** Hosts that put idle services to sleep make the first request slow.

Note the exact public URL once it is up, for example `https://agriscout-api.example.com`.

### Environment variables

| Variable | Set it to | Why |
|---|---|---|
| `AGRISCOUT_SECRET` | a long random string | Signs one-time codes and tokens. If unset, the container generates a random one each start (sessions reset on restart). |
| `AGRISCOUT_ADMIN_KEY` | a long random string | Protects `/admin` and the simulator. **If unset it is the public default `demo-admin`**, which lets anyone run and reset analyses. |
| `AGRISCOUT_CORS_ORIGINS` | your Vercel URL, e.g. `https://agriscout.vercel.app` | The browser only lets the site call the API from allowed origins. Comma-separate several. No trailing slash. `http://localhost:5173` is always allowed. |
| `AGRISCOUT_CORS_REGEX` | optional, e.g. `https://agriscout-.*\.vercel\.app` | Also allow Vercel preview deployments, whose URLs change on every push. |
| `AGRISCOUT_DEMO` | `1` (default) or `0` | At `1`, `/api/dev/sms` exposes the mock SMS outbox **including one-time codes**, which is what makes the on-screen Demo phone work. At `0` the Demo phone shows nothing and nobody can sign in, because there is no real SMS gateway. |

## 2. Deploy the frontend on Vercel

### From the Vercel dashboard

1. Make sure the deployment files are on GitHub (`git push`); Vercel builds from the repository.
2. On Vercel: **Add New > Project**, import the repository.
3. Set **Root Directory** to `frontend`. Vercel detects Vite on its own; leave the build command and output directory at their defaults. `frontend/vercel.json` already rewrites every path to `index.html`, so refreshing `/farmer/dashboard` or `/admin/simulate` works.
4. Under **Environment Variables**, add `VITE_API_URL` = your API's public URL from step 1, with **no trailing slash**.
5. **Deploy.**

### From the command line

```bash
cd frontend
npx vercel login
npx vercel env add VITE_API_URL production      # paste the API URL when asked
npx vercel --prod
```

`VITE_API_URL` is baked into the JavaScript at build time. **Changing it requires a redeploy.**

## 3. Connect them

1. Copy the Vercel site's URL (for example `https://agriscout.vercel.app`).
2. Set it as `AGRISCOUT_CORS_ORIGINS` on the API and restart the API.
3. Open the Vercel site and check:
   - `/farmer`: sign in as `MDY-001`, open the **Demo phone**, enter the code. You should see a real rice field with one flagged patch, dated three weeks ago.
   - `/operator`: operator `OP-MAD`, PIN `1234`, farmer `MDY-002`: the assisted flow.
   - `/admin` then **Survey-day simulator**: enter your `AGRISCOUT_ADMIN_KEY`, then **Start survey day**. Three farms analyse in about ten seconds on a small instance, longer on a slow one.

## What the hosted demo is, and is not

- **It is a public demo with fictional data.** With `AGRISCOUT_DEMO=1` anyone can read any one-time code, so anyone can sign in as any demo farmer. Never put real farmer data behind it.
- **SMS is a mock.** Real delivery needs a gateway implementation of `backend/app/sms.py`, a DLT-registered sender and approved templates.
- **Farmer `MDY-003` has no survey until you run the simulator,** which flies that farm's first survey. The optional real-maize field is not shipped (it is not part of `deploy/demo-data/`).
- **Simulated damage.** The imagery is real, but the crop damage on the rice farms is generated and blended in; every screen and PDF says so.
- Reports are rendered on Linux with Noto fonts, so their typography differs slightly from the Windows-rendered screenshots in the README.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Browser console: *blocked by CORS policy* | The Vercel URL is not in `AGRISCOUT_CORS_ORIGINS` (check scheme, no trailing slash) or the API has not restarted since you set it. Preview URLs need `AGRISCOUT_CORS_REGEX`. |
| Calls go to the Vercel domain and return 404 | `VITE_API_URL` was empty at build time. Set it and **redeploy**. |
| Calls blocked as *mixed content* | The API URL is `http://`. Use `https://`. |
| Refreshing a page gives 404 | `frontend/vercel.json` was not picked up: confirm Root Directory is `frontend`. |
| Demo phone is empty / cannot sign in | `AGRISCOUT_DEMO` is `0`, or the API restarted and you are using an old code. Request a new one. |
| Admin page says *403* | The key you typed is not the API's `AGRISCOUT_ADMIN_KEY`. The page prefills `demo-admin`; replace it. |
| Container is killed or analyses fail | Out of memory. Use an instance with 2 GB or more. |
| Reports show boxes instead of Kannada | The container lost its fonts: the Dockerfile installs `fonts-noto-core`; do not strip it. |

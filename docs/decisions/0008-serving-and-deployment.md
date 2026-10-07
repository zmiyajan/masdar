# ADR-0008: Serving and deployment

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Masdar has to reach three kinds of user: people (HR, legal and compliance teams, and recruiters
looking at a portfolio), programs (a JSON API), and AI agents (MCP). The demo must be public and
free to run, and it must not weaken the guarantees the rest of the project makes: every answer is
a cited article, and what is evaluated is what is served.

## Decision

### One `SearchService` behind every surface
The FastAPI app, the MCP server, the CLI and the evaluation all call the same
`masdar.app.search.SearchService`, built by the composition root. The entrypoints only validate
input and present results. Presentation is shared too (`entrypoints/schemas.py`), so an agent
over MCP receives the same citation, status label and source link that a person sees in the
browser.
- The evaluation numbers describe the production pipeline exactly. A second "API pipeline"
  would drift from the measured one without anyone noticing.
- The service is built **once**, in the app's lifespan (in a worker thread, since indexing is
  CPU-bound), never per request.
- Which pipeline is served is one setting, `MASDAR_PIPELINE` (default `dense+rerank`), resolved
  by `container.default_search_service`; an unknown name fails start-up with the valid names.

### No frontend framework
The UI is three static files (`index.html`, `app.js`, `styles.css`), served by the same process,
with no build step and no CDN JavaScript.
- The page has one job (ask, read cited articles), so a framework would add a toolchain, a
  dependency surface and supply-chain risk without adding capability.
- With no bundler, what is in the repository is exactly what runs, and the strict CSP below needs
  no hashes or nonces.
- Law text is inserted only as DOM text nodes (`textContent`), never as HTML. A test fails the
  build if `innerHTML`, `insertAdjacentHTML` or `document.write` appears.
- Highlighting folds the same Arabic variants as the server's normalizer (diacritics, tatweel,
  alef and hamza forms, taa marbuta, Arabic-Indic digits), so a highlighted word is one the
  search could have matched.

### Security headers and rate limit
| Control | Setting | Why |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'`; scripts from self only; styles from self and Google Fonts; fonts from self and `fonts.gstatic.com`; `object-src 'none'`; `base-uri 'self'`; `form-action 'self'` | Injected markup cannot execute or exfiltrate. |
| `frame-ancestors` | `'self' https://huggingface.co` | The Space page embeds the app in an iframe; any other site framing it is refused (clickjacking). This is also why there is no `X-Frame-Options: DENY`. |
| `/docs` only | Adds `cdn.jsdelivr.net` and `'unsafe-inline'` | FastAPI's Swagger UI uses an inline bootstrap script and CDN assets. It is a developer page with no user content, so it gets a narrow exception instead of weakening the app's policy. ReDoc is disabled. |
| `X-Content-Type-Options` | `nosniff` | No MIME sniffing of API responses. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Questions in the URL are not leaked to the official portal when a user follows a source link. |
| `Permissions-Policy`, `Cross-Origin-Opener-Policy` | Deny camera, microphone and geolocation; `same-origin` | Least privilege. |
| Rate limit | 30 requests per minute per client IP on `/api/*` (sliding window, in memory, bounded to 10,000 clients); `/api/health` and static files are exempt; 429 with `Retry-After` | One visitor cannot starve a single free CPU. A sliding window cannot be gamed at minute boundaries. |
| Errors | One envelope `{"error": {code, message, message_ar}}`; domain validation errors are 422; a catch-all returns a generic 500 | Users get an Arabic explanation, and tracebacks or internal messages never leave the server (tested). |

### Hugging Face Spaces
- **Free CPU hardware** (2 vCPU, 16 GB RAM) fits the whole pipeline: BM25, a small embedding
  model and a reranker over about 540 chunks.
- **The Docker SDK** runs the same image locally and in production, and the image is the
  artifact under review.
- **It is the expected home for AI portfolio demos**: reviewers can open it with one click, and
  the Space page links back to the code and the dataset.
- The image is multi-stage (uv only in the builder), installs exactly `uv.lock`, copies an
  allow-list of files, runs as UID 1000 (a Spaces requirement), listens on port 7860 and has a
  `HEALTHCHECK` on `/api/health`.

### Cold start: warm up at build time
Spaces sleep when idle, and a cold start that also downloads models and builds indexes would
make the first visitor wait minutes. The Dockerfile runs `python -m masdar.entrypoints.warmup` as
the runtime user, with `HF_HOME` inside the image, so model weights (and any index the container
caches on disk) are baked into the image. The step is `|| true`: a build without network still
produces a working image that warms up on first start instead.

## Consequences
- ✅ One measured pipeline: an improvement in `make eval` is an improvement in the demo and the
  MCP tool.
- ✅ The UI is about 32 KB of unminified first-party code with nothing to build, audit or upgrade.
- ✅ The page cannot run injected script, even if a source document contained markup.
- ⚠️ **The rate limit is per process and in memory.** It resets on restart and does not span
  replicas; scaling out needs a shared store (for example Redis). It keys on the `X-Forwarded-For`
  entry written by our own edge proxy (`MASDAR_TRUSTED_PROXY_HOPS`, counted from the right),
  never on entries a client can send, so a forged header gets no fresh bucket. Model inference
  is serialised by a lock in each model adapter: tokenizers are not thread-safe, and two
  vCPUs gain nothing from parallel forward passes. It protects a demo from accidental overload, not from a
  determined attacker.
- ⚠️ **Google Fonts** is the one third-party request: visitors' IP addresses reach Google. It can
  be removed by self-hosting the two font families under `web/` and dropping the two Google hosts
  from the CSP. The system fallbacks keep the page readable if the fonts are blocked.
- ⚠️ **Warm-up only persists what is on disk.** In-memory indexes are rebuilt at every process
  start; that cost is bounded by the corpus size (seconds).
- ⚠️ **Image size.** The `ml` extra pulls PyTorch, and the lockfile resolves the CUDA build on
  Linux, which adds gigabytes the CPU Space never uses. A CPU-only PyTorch index in
  `pyproject.toml` would shrink the image substantially.
- ⚠️ The demo answers questions with articles. It does not give legal advice, and the UI says so
  on every page.

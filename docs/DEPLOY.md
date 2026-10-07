# Deploying Masdar

Masdar ships as one container: the web UI, the JSON API and the OpenAPI docs, served by uvicorn
on port 7860. The public demo runs on Hugging Face Spaces (free CPU, Docker SDK). The reasoning
is in [ADR-0008](decisions/0008-serving-and-deployment.md).

## 1. Run locally (no Docker)

```bash
make setup     # once: dependencies (including the ML extra) and git hooks
make serve     # http://localhost:8000  (UI at /, API docs at /docs)
make mcp       # optional: the MCP server on stdio, for desktop AI agents
```

Quick checks while it runs:

```bash
curl -s localhost:8000/api/health
curl -s -G localhost:8000/api/search --data-urlencode "q=كم مدة إجازة الأمومة؟" --data-urlencode "k=3"
curl -s localhost:8000/api/laws
```

The first start builds the search indexes (and downloads the embedding models if the dense
pipeline is enabled), so it is slower than later ones.

### Use the MCP server from an agent
Add this to the agent's MCP configuration (for example Claude Desktop's
`claude_desktop_config.json`), with the absolute path to your checkout:

```json
{
  "mcpServers": {
    "masdar": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/masdar", "masdar-mcp"]
    }
  }
}
```

It exposes `search_regulations(query, k=5, law=None)` and `get_article(article_id)`.

## 2. Build and run the container

```bash
docker build -t masdar .
docker run --rm -p 7860:7860 masdar      # http://localhost:7860
docker inspect --format '{{.State.Health.Status}}' <container-id>   # "healthy" after start-up
```

The image:
- is multi-stage (uv in the builder only) on `python:3.12-slim-bookworm`;
- installs exactly `uv.lock` with `uv sync --frozen --no-dev --extra ml`;
- copies only `src/`, `data/sources/`, `data/gold/`, `data/dataset/stats.json` and
  `DATASET_CARD.md` (`.dockerignore` is an allow-list);
- runs as the non-root user UID 1000, which Spaces requires;
- runs `python -m masdar.entrypoints.warmup` at build time, so model weights and any on-disk
  index ship inside the image;
- has a `HEALTHCHECK` on `/api/health`.

Settings can be overridden with `MASDAR_*` environment variables (see `src/masdar/config.py`),
for example `docker run -e MASDAR_DATASET_DIR=/app/data/dataset ...`.

## 3. Publish to Hugging Face Spaces

> **Before publishing:** the owner approves the release. Publishing makes the demo public.

A Space is a git repository whose root `README.md` is the Space card. Masdar keeps that card in
[`deploy/huggingface/README.md`](../deploy/huggingface/README.md). It replaces the project
README **only in the Space**, never in this repository.

### One-time setup
1. Create a Hugging Face account and a **write** access token (Settings, then Access Tokens).
2. Install the CLI (`hf`, from `huggingface_hub` 1.x; these commands were checked against
   1.33) and log in:
   ```bash
   uv tool install huggingface_hub
   hf auth login                     # paste the write token
   ```
3. Create the Space (Docker SDK, free CPU hardware):
   ```bash
   hf repo create <hf-user>/masdar --repo-type space --space-sdk docker
   ```

### Option A: upload with the CLI (recommended)
Stage a clean copy of the committed tree, swap in the Space card, and upload it:

```bash
STAGE="$(mktemp -d)"
git archive HEAD | tar -x -C "$STAGE"
cp deploy/huggingface/README.md "$STAGE/README.md"
hf upload <hf-user>/masdar "$STAGE" . --repo-type space \
  --commit-message "Deploy $(git rev-parse --short HEAD)"
```

`git archive` sends only committed files, so local caches, `.venv` and `.env` can never leak.

### Option B: git push to the Space repository

```bash
git clone https://huggingface.co/spaces/<hf-user>/masdar ../masdar-space
git archive HEAD | tar -x -C ../masdar-space
cp deploy/huggingface/README.md ../masdar-space/README.md
cd ../masdar-space
git add -A && git commit -m "Deploy masdar $(git -C ../masdar rev-parse --short HEAD)"
git push        # authenticate with your HF username and the write token
```

### After pushing
- The Space builds the Dockerfile; follow progress in the Space's **Logs** tab.
- When it shows **Running**, open `https://<hf-user>-masdar.hf.space/api/health`.
- Try the four example questions in the UI and check that the citations and source links work.
- No secrets are needed: the core runs on local models only.

### Rolling back
Every upload is a commit in the Space repository. Revert it there (in the web UI under
**Files**, then **History**, or with `git revert` in the Space clone) and the Space rebuilds the
previous version.

## Limits of the free CPU Space
- One process and one in-memory rate limiter (30 requests per minute per client). Scaling out
  needs a shared limiter (for example Redis).
- Spaces sleep after inactivity; the first request after a sleep waits for a cold start. The
  build-time warm-up keeps that to process start-up and index loading, without downloads.
- See ADR-0008 for the full list.

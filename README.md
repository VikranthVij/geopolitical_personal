# Geopolitical OSINT Intelligence Dashboard

Local-first intelligence workspace for turning public reporting into traceable event threads, incidents, claims, evidence, and India-impact analysis. The article is stored as provenance; it is not treated as the intelligence identity. See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the engineering source of truth and [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) for current scope and known gaps.

## Start locally

Requirements: Docker Desktop with Compose, 4 GB+ memory recommended. Ollama is optional.

```sh
cp .env.example .env
# Change POSTGRES_PASSWORD and the matching password in DATABASE_URL in .env.
docker compose up --build
```

Open the dashboard at http://localhost:3000 and API docs at http://localhost:8000/docs. PostgreSQL listens only inside the Compose network. Data persists in the `postgres_data` volume. Stop with `docker compose down`; preserve data by not adding `-v`.

To enable local generated answers, install Ollama, start its service, then run `ollama pull qwen2.5:7b` and `ollama pull nomic-embed-text`. Set `OLLAMA_BASE_URL` if Ollama is not on the host's default address. The database and source collector do not depend on Ollama.

## Development checks

```sh
python3 -m unittest discover -s backend/tests -v
python3 -m compileall -q backend/app backend/tests
docker compose config
```

Frontend build (requires Node.js and npm):

```sh
cd frontend
npm install
npm run build
```

## API

- `GET /health`, `GET /events?section=india|global|other|all`
- `GET /events/{id}`, `/timeline`, `/evidence`, `/history`, `/india-impact`, `/changes`
- `POST /events/{id}/ask` with `{"question":"..."}`; answers are returned only when Ollama provides verifiable stored-claim citations, otherwise generated conclusions are withheld.
- `POST /events/{id}/watch` toggles watch; `GET /watchlist`
- `POST /collection/run` starts an on-demand run; `GET /collection/runs` shows run history.

## Operations and privacy

The initial feed list is intentionally small and editable in `backend/app/default_feeds.py`. On first run it scans up to 60 days of RSS items by default because some official feeds refresh slowly; URLs and content hashes prevent repeat processing. Review publisher terms before enabling additional feeds or retaining excerpts. Collection records per-feed errors and continues with other feeds. Migrations are checked into `backend/migrations` and run once under a PostgreSQL advisory lock. Back up through standard PostgreSQL tools; database dumps are local user data and must not be committed.

Do not expose the API or database directly to the public internet. Private remote access through Tailscale requires device/account authorization on the user's Mac and is not enabled by this project.

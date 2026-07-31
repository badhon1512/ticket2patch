# Ticket2Patch activity dashboard

Next.js dashboard for viewing persisted Ticket2Patch runs and their ordered
activity timelines.

## Run locally

Start PostgreSQL from the repository root:

```powershell
docker compose -f deployment/docker-compose.yml up -d postgres
```

Start the backend API from `backend`:

```powershell
uv run uvicorn app.api.main:app --reload --port 8000
```

Start the frontend in another terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

- `/` shows persisted runs and their activity timelines.
- `/chat` provides a browser conversation with the LangGraph agent.

The dashboard polls the API every four seconds. Agent activity is created when
the local CLI runs:

```powershell
uv run python -m app.cli --owner badhon1512 --repo ticket2patch
```

# AI Counsel

Local-first equity research and paper-trading desktop app. Discovery scoring, multi-role counsel, tax ledger, and Autopilot all run against free or optional local data sources (Yahoo, public SEC, optional free Alpaca paper keys, optional FRED, Ollama).

## Stack

| Layer | Technology |
|-------|------------|
| Desktop | Tauri 2 |
| UI | React, TypeScript, Vite, Tailwind CSS |
| Backend | Python, FastAPI |
| Local LLMs | Ollama |
| Storage | SQLite |

## Prerequisites

- Node.js 20+
- Python 3.11+
- Rust (rustc + cargo) for the Tauri desktop shell ([rustup](https://rustup.rs/))
- Ollama (optional) at `http://127.0.0.1:11434`

## Setup

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env

cd frontend
npm install
cd ..
```

## Run the backend

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

## Run the UI (Vite)

```bash
cd frontend
npm run dev
```

Open the URL Vite prints (usually http://127.0.0.1:1420).

## Run the Tauri desktop app

From the repo root:

```bash
npm install
npm run tauri:dev
```

Start the FastAPI backend separately before using live health or Autopilot features.

```bash
npm run tauri:build
```

## Features

- Stock discovery (invest / daytrade / swing lanes) with deterministic Python scoring
- Found-stocks archive, paper book, and tax ledger (lots, wash blocks, T+1 settlement)
- Autopilot multi-role crew with Python consensus, Kelly sizing (~6% cap), and kill switch
- Optional Alpaca paper or live keys (user-supplied); default mode is local paper

## Configuration

- `config.yaml` - research limits, scoring weights, trading risk gates, model registry
- `.env.example` - host/port, DB path, Ollama URL
- Secrets stay in `backend/data/secrets.local.json` (gitignored)

Paid APIs are never required. Add keys in Settings only if you choose to.

## Tests

```bash
pytest
```

## Project layout

```text
ai-counsel/
+-- frontend/          # React + Vite UI
+-- src-tauri/         # Tauri 2 desktop shell
+-- backend/           # FastAPI backend
+-- schemas/           # Shared JSON schemas
+-- prompts/           # Agent prompt templates
+-- tests/             # Pytest suite
+-- docs/              # Architecture notes
+-- config.yaml
```

## License

MIT. Research and trading tools are informational. You are responsible for compliance with broker rules and tax law.

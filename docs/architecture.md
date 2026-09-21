# AI Counsel Architecture

Local-first desktop research app: Tauri + React UI talks to a FastAPI backend on localhost.

```text
Tauri Desktop (React + TS)
        |
   Local HTTP API
        |
   FastAPI Core
        |
 +------+--------------+
 |      |              |
Research Counsel   Scoring
 Engine   Engine    Engine
 |      |              |
 Market / Web   Evidence Store (SQLite)
 Providers
 |
 LLM Providers (Ollama primary)
```

Core rule: LLMs are researchers and critics. Numerical scores come from deterministic Python rules backed by `EvidenceItem` records.

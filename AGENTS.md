# Repository Guidelines

## Project Structure & Module Organization

- `backend/` contains the FastAPI service. Application code lives in `backend/app/`; routers define HTTP endpoints, services contain RAG, retrieval, document ingestion, and settings logic, and SQLAlchemy models are centralized in `app/models.py`.
- `frontend/` contains the Vue 3 application. Pages live in `src/views/`, shared layout in `src/components/`, routes in `src/router/index.js`, and global state/API helpers in `src/store.js`.
- `docs/` stores the Chinese requirements, architecture, and feature-specific design documents.
- Local runtime data is intentionally untracked: `backend/uploads/`, `backend/chroma_data/`, `backend/.venv/`, and generated frontend bundles.

## Build, Test, and Development Commands

Backend setup and run:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
.venv\Scripts\python run.py
```

Use `run.py` on Windows because it selects the required psycopg event loop.

Frontend development and verification:

```bash
cd frontend
npm install
npm run dev
npm run build
```

There is no automated test suite yet. Before submitting changes, run Python compilation for touched modules and `npm run build` for frontend changes.

## Coding Style & Naming Conventions

- Keep Python modules simple and readable; use 4-space indentation, type hints for public functions, and Chinese user-facing messages.
- Name files in Python with `snake_case`, Vue files with `PascalCase`, and router paths with lowercase kebab-style segments.
- Vue files should keep business logic in `<script setup>` and scoped styles in the same component.
- Reuse CSS variables from `frontend/src/style.css`; avoid hard-coding new theme colors when a token exists.
- Prefer small, focused changes that align with existing service/router boundaries.

## Testing Guidelines

- Place future Python tests under `backend/tests/` using `test_<module>.py`.
- Place future frontend component tests under `frontend/tests/` using `<component>.spec.js`.
- For RAG or retrieval changes, document the manual test question, expected source scope, and any metadata checks in the PR description.

## Commit & Pull Request Guidelines

No commit history exists yet. Use concise, imperative commit subjects such as `feat: add hybrid retrieval` or `fix: prevent empty KB selection`.

Pull requests should include:

- Purpose and user-visible behavior changes.
- Screenshots for UI changes.
- Verification commands and results.
- Notes about configuration, migration, or vector-index compatibility.

## Security & Configuration Tips

- Never commit `backend/.env`, API keys, uploaded documents, or generated vector data.
- Keep secrets in environment variables and local-only configuration files.
- Preserve JWT, password hashing, and admin-only permission checks when changing authentication flows.

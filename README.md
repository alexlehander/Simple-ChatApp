# One-Command Deployment (Frontend + Backend + MySQL)

This starter pack lets you run your project with **Docker Compose** on a clean laptop.

## Folder setup (expected layout)

Place these files at the same level as your extracted project:

```
your-project-root/
├─ LLM_BACKEND/
│  └─ LLM_BACKEND-main/           # from LLM_BACKEND.zip
│     ├─ app.py
│     └─ requirements.txt
├─ LLM_FRONTEND/
│  └─ LLM_FRONTEND-main/          # from LLM_FRONTEND.zip
│     ├─ app_chat.py
│     └─ requirements.txt
├─ railway_chat_log.sql
├─ railway_respuesta_usuario.sql
├─ railway_usuario.sql
├─ backend.Dockerfile
├─ frontend.Dockerfile
├─ docker-compose.yml
├─ .env           # create from .env.example
└─ db_init/       # put the .sql files here (see below)
```

## 0) Prereqs

- Install **Docker Desktop** (Win/Mac) or **Docker Engine** (Linux).
- (Optional) Install **git** and a code editor (VS Code).

## 1) Make two small code edits

**A. Backend (`LLM_BACKEND/LLM_BACKEND-main/app.py`)**

Replace hard-coded secrets with environment variables:

```python
# add near the top
import os
openai.api_key = os.getenv("OPENAI_API_KEY")

# replace SQLALCHEMY_DATABASE_URI with:
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://app:app@db:3306/llmapp"
)
```

**B. Frontend (`LLM_FRONTEND/LLM_FRONTEND-main/app_chat.py`)**

Replace hard-coded URLs with an env-based base URL:

```python
import os
BASE = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_GENERAR_CODIGO    = f"{BASE}/generar_codigo"
BACKEND_URL_CHAT             = f"{BASE}/chat"
BACKEND_URL_VERIFICAR        = f"{BASE}/verificar_respuesta"
BACKEND_URL_OBTENER_PROBLEMA = f"{BASE}/obtener_problema"
```

## 2) Put SQL dumps into `db_init/`

Move these three files to the `db_init` folder:

- `railway_chat_log.sql`
- `railway_respuesta_usuario.sql`
- `railway_usuario.sql`

They will auto-import on the first DB start.

## 3) Create `.env`

Copy `.env.example` to `.env` and set your OpenAI key:

```
OPENAI_API_KEY=sk-...
```

## 4) Build & run

```bash
docker compose up -d --build
```

- Frontend (Flet web): http://localhost:3000
- Backend (Flask API): http://localhost:8000
- MySQL (inside network): db:3306 (or localhost:3306 on your machine)

## 5) Logs & troubleshooting

- Watch all logs:
  ```bash
  docker compose logs -f
  ```
- If DB import fails, check DB logs:
  ```bash
  docker compose logs -f db
  ```
- If backend can’t connect to DB, ensure `DATABASE_URL` is correct and that backend waits until DB is ready (Compose handles basic ordering with `depends_on`).

## Common pitfalls

- **Port conflicts:** If 3000/8000/3306 are used, change the left side of the port mappings in `docker-compose.yml`.
- **Wrong paths:** Ensure the inner zips were extracted to `LLM_BACKEND/LLM_BACKEND-main/` and `LLM_FRONTEND/LLM_FRONTEND-main/`.
- **Secrets in code:** Make sure `app.py` uses `OPENAI_API_KEY` and not a hard-coded value.

# DocuFix API

Account, plan, and file-history service. Image and PDF processing stay in the browser. This API stores account records and history metadata only. It does not store document contents.

## Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer only when `DATABASE_URL` points at PostgreSQL. The local default is a SQLite file.

Tests use a temporary SQLite database and do not connect to PostgreSQL.

## Setup (Windows PowerShell)

From the `backend` folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Replace `SECRET_KEY` in `.env` with a random string of at least 24 characters. The example value is rejected on startup. Leave `DATABASE_URL` as the SQLite file unless PostgreSQL accepts the user you configure. Then apply migrations:

```powershell
alembic upgrade head
```

Start the API:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger UI is at http://127.0.0.1:8000/docs.

## Tests

```powershell
python -m pytest
```

## Authentication

Login and registration create a random session token. The hash is stored in the database. The browser receives it in an HttpOnly cookie. `POST /api/auth/logout` marks that session revoked, so the token stops working. An expired row is rejected with `Token has expired.`

There is no endpoint that lets a client set its own plan. `billing_connected` is always false.

## History

`POST /api/history` records a filename, operation, sizes, and status for the signed-in user. The response field `download_available` is false because the file itself is not uploaded.

# Automotive Arbitrage

Backend foundation for Germany → Ukraine vehicle arbitrage.

## Local start

1. `python -m venv .venv`
2. `\.venv\Scripts\python -m pip install -e ".[dev]"`
3. Copy `.env.example` to `.env` when overriding the database URL.
4. `docker compose up -d postgres`
5. `\.venv\Scripts\alembic upgrade head`

Generate migration SQL without connecting to PostgreSQL:

`\.venv\Scripts\alembic upgrade head --sql`

The first migration creates `source`, `listing`, `vehicle`, `vehicle_link`, and `vehicle_snapshot`.


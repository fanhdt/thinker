# Thinker

Thinker adalah sistem AI personal yang dibangun bertahap (Fase 0 - Fase 9) sebagai proyek belajar Python + AI Engineering. Bukan chatbot biasa -- Thinker punya memori jangka panjang, RAG atas dokumen, planner dengan reflection loop, dan personalisasi, semua dirakit dari fondasi rekayasa perangkat lunak yang eksplisit (testing, type checking, migrations) sejak Fase 0.

Lihat [`ARCHITECTURE.md`](./ARCHITECTURE.md) untuk penjelasan desain sistem, dan [`DECISIONS.md`](./DECISIONS.md) untuk riwayat keputusan teknis (format ADR).

## Tech Stack

| Layer              | Teknologi                                                                                  |
| ------------------ | ------------------------------------------------------------------------------------------ |
| Backend            | Python 3.12, FastAPI, Pydantic                                                             |
| Database           | PostgreSQL, SQLAlchemy (async), Alembic                                                    |
| LLM                | Google Gemini (`google-genai`), diakses lewat abstraksi `Protocol` (lihat ARCHITECTURE.md) |
| Package management | [uv](https://docs.astral.sh/uv/)                                                           |
| Type checking      | pyright                                                                                    |
| Linting            | ruff                                                                                       |
| Testing            | pytest + pytest-asyncio                                                                    |
| Infrastruktur      | Docker, Docker Compose                                                                     |

## Prasyarat

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (untuk PostgreSQL)
- API key Gemini ([Google AI Studio](https://aistudio.google.com/apikey))

## Setup

```bash
git clone https://github.com/fanhdt/thinker.git
cd thinker/backend

# install dependency + buat virtualenv
uv sync

# siapkan konfigurasi
cp .env.example .env
# lalu isi GEMINI_API_KEY di .env dengan API key Anda sendiri

# nyalakan PostgreSQL
cd ..
docker compose up -d db

# jalankan migration
cd backend
uv run alembic upgrade head

# jalankan server
uv run uvicorn app.main:app --reload
```

Server jalan di `http://localhost:8000`. Dokumentasi API interaktif (Swagger) ada di `http://localhost:8000/docs`.

**PENTING**: `.env` berisi secret (API key) dan sudah di-gitignore -- jangan pernah commit file ini. Kalau API key pernah tidak sengaja terekspos (misal ke chat, screenshot, atau commit), revoke dan buat yang baru di Google AI Studio.

## Menjalankan Test & Type Check

```bash
cd backend

# jalankan semua test
uv run pytest

# jalankan type checker (harus 0 error di app/, exclude alembic/)
uv run pyright app/

# jalankan linter
uv run ruff check .
```

Test dibagi dua level: **unit test** (menguji fungsi service secara langsung, mis. `test_planner_service.py`, `test_memory_service.py`) dan **test API/HTTP-level** (menguji lewat `TestClient` FastAPI sungguhan, mis. `test_conversations_api.py`, `test_goals_api.py`). Lihat `tests/conftest.py` untuk fixture `client` yang dipakai bersama semua test API.

## Ringkasan API

| Method | Path                           | Deskripsi                                                       |
| ------ | ------------------------------ | --------------------------------------------------------------- |
| POST   | `/conversations`               | Buat percakapan baru                                            |
| GET    | `/conversations/{id}/messages` | Ambil riwayat pesan                                             |
| POST   | `/conversations/{id}/messages` | Kirim pesan (menyatukan memori, RAG, goals, orchestrator)       |
| POST   | `/conversations/{id}/plan`     | Buat & eksekusi plan untuk sebuah goal (dengan reflection loop) |
| POST   | `/documents`                   | Upload & indeks dokumen (untuk RAG)                             |
| GET    | `/documents`                   | Daftar dokumen yang sudah diupload                              |
| GET    | `/memories`                    | Daftar memori jangka panjang yang tersimpan                     |
| POST   | `/goals`                       | Buat goal baru                                                  |
| GET    | `/goals`                       | Daftar goal (bisa difilter `?status=`)                          |
| PATCH  | `/goals/{id}`                  | Ubah status goal                                                |
| GET    | `/profile`                     | Ambil profil user (nama, preferensi)                            |
| PATCH  | `/profile`                     | Update profil / merge preferensi                                |
| POST   | `/chat`                        | Endpoint chat sederhana tanpa riwayat (peninggalan Fase 1)      |
| GET    | `/health`                      | Health check                                                    |

## Status Pengembangan

Semua 9 fase yang direncanakan (fondasi -> chat dasar -> percakapan -> memori -> RAG -> tools -> planner -> reflection -> personalisasi -> integrasi) sudah diimplementasikan. Yang masih jadi keterbatasan yang disadari (bukan bug) -- lihat bagian "Keterbatasan yang Diketahui" di `ARCHITECTURE.md`.

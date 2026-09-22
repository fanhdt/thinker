# Thinker

Thinker adalah sistem AI personal yang dibangun bertahap (Fase 0 - Fase 9) sebagai proyek belajar Python + AI Engineering. Bukan chatbot biasa -- Thinker punya memori jangka panjang (dengan operasi CREATE/UPDATE/DELETE, bukan cuma tambah), RAG atas dokumen, planner dengan reflection loop, personalisasi, dan **arsitektur LLM yang model-agnostic** (bisa pakai Gemini, OpenAI, Groq, DeepSeek, atau OpenRouter -- termasuk failover otomatis antar provider), semua dirakit dari fondasi rekayasa perangkat lunak yang eksplisit (testing, type checking, migrations, structured logging) sejak Fase 0.

Lihat [`ARCHITECTURE.md`](./ARCHITECTURE.md) untuk penjelasan desain sistem, dan [`DECISIONS.md`](./DECISIONS.md) untuk riwayat keputusan teknis (format ADR).

## Tech Stack

| Layer              | Teknologi                                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| Backend            | Python 3.12, FastAPI, Pydantic                                                                                            |
| Database           | PostgreSQL, SQLAlchemy (async), Alembic                                                                                   |
| LLM                | Model-agnostic (Gemini / OpenAI / Groq / DeepSeek / OpenRouter) lewat abstraksi `LLMProvider` -- lihat ARCHITECTURE.md §5 |
| Package management | [uv](https://docs.astral.sh/uv/)                                                                                          |
| Type checking      | pyright                                                                                                                   |
| Linting            | ruff                                                                                                                      |
| Testing            | pytest + pytest-asyncio                                                                                                   |
| Logging            | JSON terstruktur (`app/core/logging_config.py`) -- lihat ARCHITECTURE.md §10                                              |
| Infrastruktur      | Docker, Docker Compose                                                                                                    |

## Prasyarat

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (untuk PostgreSQL)
- API key dari **minimal satu** provider LLM: [Gemini](https://aistudio.google.com/apikey), [OpenAI](https://platform.openai.com/api-keys), [Groq](https://console.groq.com/keys), [DeepSeek](https://platform.deepseek.com/api_keys), atau [OpenRouter](https://openrouter.ai/keys). Gemini tetap dibutuhkan untuk fitur memori/RAG (lihat catatan di bawah).

## Setup

```bash
git clone https://github.com/fanhdt/thinker.git
cd thinker/backend

# install dependency + buat virtualenv
uv sync

# siapkan konfigurasi
cp .env.example .env
# lalu isi minimal GEMINI_API_KEY (default LLM_PROVIDER=gemini)

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

**PENTING**: `.env` berisi secret (API key) dan sudah di-gitignore -- jangan pernah commit file ini. Kalau API key pernah tidak sengaja terekspos (misal ke chat, screenshot, atau commit), revoke dan buat yang baru di dashboard provider terkait.

### Memilih provider LLM

Default-nya Gemini (`LLM_PROVIDER=gemini`), tapi bisa diganti ke provider lain -- atau dikombinasikan -- tanpa mengubah kode sama sekali, cukup lewat `.env`:

```dotenv
# Pilih satu provider tunggal:
LLM_PROVIDER=groq
GROQ_API_KEY=isi-key-groq-anda

# ATAU rantai failover otomatis -- kalau satu gagal (kuota habis, error,
# saldo habis), otomatis coba yang berikutnya:
LLM_PROVIDER_CHAIN=gemini,openrouter,groq,deepseek

# ATAU beberapa API key untuk provider YANG SAMA (mis. 2 project Gemini
# gratis berbeda), dipisah koma -- otomatis gantian kalau satu kena limit:
GEMINI_API_KEY=key-project-1,key-project-2

# ATAU provider berbeda untuk task ringan (chat, routing) vs task planner
# (eksekusi+evaluasi, paling berat reasoning-nya):
LLM_PROVIDER_SIMPLE=groq
LLM_PROVIDER_PLANNER=gemini
```

Lihat `.env.example` untuk daftar lengkap variabel dan `ARCHITECTURE.md` §5-§9 untuk penjelasan desainnya.

**Catatan**: fitur memori/RAG (`EmbeddingService`) masih terikat ke Gemini (`gemini-embedding-001`) apa pun `LLM_PROVIDER` yang dipilih -- jadi `GEMINI_API_KEY` tetap perlu diisi valid meskipun provider chat/planner-nya diganti ke yang lain. Lihat "Keterbatasan yang Diketahui" di `ARCHITECTURE.md`.

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

Test dibagi dua level: **unit test** (menguji fungsi service secara langsung, mis. `test_planner_service.py`, `test_memory_service.py`, `test_gemini_provider.py`, `test_fallback_provider.py`) dan **test API/HTTP-level** (menguji lewat `TestClient` FastAPI sungguhan, mis. `test_conversations_api.py`, `test_goals_api.py`). Lihat `tests/conftest.py` untuk fixture yang dipakai bersama semua test, termasuk fixture global yang mereset `settings` (khususnya konfigurasi provider LLM) setelah tiap test yang memodifikasinya.

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

Bot Telegram (`app/telegram/bot.py`) memakai jalur pipeline yang sama (`message_pipeline.process_incoming_message`) dengan `POST /conversations/{id}/messages` -- bukan implementasi terpisah.

## Status Pengembangan

Semua 9 fase yang direncanakan (fondasi -> chat dasar -> percakapan -> memori -> RAG -> tools -> planner -> reflection -> personalisasi -> integrasi) sudah diimplementasikan. Di atas itu, sudah ditambahkan:

- **Observability**: structured JSON logging di semua service (`log_event`), request-id per request, event untuk tiap panggilan LLM (durasi, token, provider, tools yang dipanggil).
- **Reliability**: error rate-limit (429) dari LLM diteruskan sebagai HTTP 429 dengan pesan yang jelas (bukan 503 generik); kegagalan sebagian (mis. task planner yang tidak menghasilkan jawaban) tidak lagi menjatuhkan seluruh percakapan.
- **Efisiensi panggilan LLM**: beberapa panggilan yang dulu terpisah digabung jadi satu (classify+plan, execute+evaluate) -- kira-kira separuh jumlah panggilan LLM per plan dibanding sebelumnya.
- **Model-Agnostic Architecture** (lihat ARCHITECTURE.md §5): dukungan Gemini/OpenAI/Groq/DeepSeek/OpenRouter, failover otomatis antar provider, multi-key per provider, dan routing task ringan vs planner ke provider berbeda.

Yang masih jadi keterbatasan yang disadari (bukan bug) -- lihat bagian "Keterbatasan yang Diketahui" di `ARCHITECTURE.md`.

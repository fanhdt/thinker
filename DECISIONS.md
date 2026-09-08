# Riwayat Keputusan Arsitektur (ADR)

Format tiap entri: Keputusan, Konteks, Opsi, Pendekatan yang dipilih, Alasan, Trade-off.

---

## ADR-001: Package Manager -- uv

**Keputusan**: Memakai `uv` untuk dependency management, virtual environment, dan lockfile.

**Konteks**: Fase 0, butuh fondasi tooling Python sebelum menulis kode aplikasi apapun.

**Opsi**:

- **pip + requirements.txt + venv manual** -- paling dasar, tanpa "magic", tapi tidak ada lockfile solid dan mudah drift antara dev/production.
- **poetry** -- dependency resolution kuat, lockfile eksplisit, tapi agak lambat dan opinionated soal struktur proyek.
- **uv** -- sangat cepat (Rust), menggabungkan venv+install+lockfile+manajemen versi Python dalam satu tool.

**Pendekatan yang dipilih**: uv.

**Alasan**: Pengalaman mirip package manager modern JS (pnpm/bun) yang sudah familiar; jadi standar baru ekosistem Python 2025-2026.

**Trade-off**: Tool relatif baru dibanding pip/poetry -- dokumentasi komunitas pihak ketiga masih tumbuh, meski tooling intinya sendiri sudah stabil.

---

## ADR-002: Konfigurasi -- pydantic-settings

**Keputusan**: Semua konfigurasi (API key, database URL, dst) dibaca lewat `pydantic_settings.BaseSettings`, bukan `os.environ` manual atau hardcode.

**Konteks**: Fase 0, prinsip "environment variables sejak awal, bukan hardcoded value".

**Opsi**:

- `os.environ.get(...)` manual di tiap tempat yang butuh -- sederhana tapi tidak ada validasi tipe, error muncul telat (runtime, jauh dari sumbernya).
- `pydantic-settings` -- validasi tipe otomatis, error muncul di titik startup (fail-fast) kalau ada field wajib yang belum diisi.

**Pendekatan yang dipilih**: pydantic-settings.

**Alasan**: Selaras dengan Pydantic yang sudah dipakai di seluruh schema API; fail-fast di startup lebih baik daripada error di tengah handling request.

**Trade-off**: Static type checker (pyright) tidak bisa memverifikasi bahwa field wajib (`gemini_api_key`) benar-benar akan terisi saat runtime (dia dibaca dari `.env`, bukan argumen constructor) -- perlu `# type: ignore[call-arg]` di titik instansiasi. Ini keterbatasan yang diketahui dan didokumentasikan di kode, bukan disembunyikan.

---

## ADR-003: Validasi Output Terstruktur dari LLM -- Helper `_as_structured`

**Keputusan**: Semua pemakaian `response.parsed` dari Gemini SDK divalidasi eksplisit lewat `isinstance()`, bukan cuma diklaim lewat anotasi tipe variabel.

**Konteks**: Ditemukan lewat audit type-checking (pyright) bahwa `response.parsed` bertipe generik (`BaseModel | dict | Enum | None`) di level SDK, sementara kode mengklaim tipe spesifik (`Plan | None`, `TaskEvaluation | None`, dst) tanpa validasi runtime.

**Opsi**:

- Biarkan seperti sebelumnya (percaya anotasi tipe) -- lebih sedikit kode, tapi kalau Gemini pernah mengembalikan bentuk tak terduga, error muncul jauh di hilir dengan pesan yang membingungkan.
- Tambah `isinstance()` check terpisah di tiap fungsi -- eksplisit tapi duplikat 4x.
- Helper terpusat `_as_structured(response, model_cls)` -- satu titik validasi, dipakai di 4 tempat.

**Pendekatan yang dipilih**: Helper terpusat.

**Alasan**: Prinsip "validasi semua input eksternal" (respons LLM adalah input eksternal, bukan sesuatu yang bisa dipercaya buta). Satu titik perbaikan kalau logikanya perlu berubah.

**Trade-off**: Fallback pada validasi gagal berbeda-beda per fungsi (`create_plan` raise, `evaluate_result`/`classify_message`/`extract_fact` fallback graceful) -- ini disengaja (lihat ARCHITECTURE.md #6), tapi berarti helper ini tidak "satu ukuran untuk semua"; pemanggil tetap harus menentukan sendiri apa yang terjadi kalau validasi gagal.

---

## ADR-004: Abstraksi LLM -- `Protocol` (PlannerLLM, OrchestratorLLM), bukan Class Konkret

**Keputusan**: `planner_service` dan `orchestrator_service` menerima parameter `llm` bertipe `Protocol` (structural typing), bukan class `LLMService` konkret.

**Konteks**: Visi awal proyek eksplisit menyebut abstraksi `LLMProvider` (OpenAI/Anthropic/Gemini/Local) supaya business logic tidak terikat provider tertentu. Sebelum refactor ini, `run_plan()`/`handle_message()` dianotasi menerima `LLMService` konkret, membuat pyright menolak `FakeLLMService` (test double) sebagai tidak valid secara tipe.

**Opsi**:

- **Tetap `LLMService` konkret** -- sederhana, tapi bertentangan langsung dengan prinsip dependency inversion yang sudah ditulis di awal proyek; test double jadi type-unsafe.
- **Abstract Base Class (ABC)** -- eksplisit, tapi `FakeLLMService` di test harus diubah untuk inherit dari ABC tersebut.
- **`typing.Protocol` (structural typing)** -- class manapun yang punya method dengan signature cocok otomatis valid, tanpa perlu inherit eksplisit.
- **Satu Protocol besar (semua method)** vs **beberapa Protocol kecil per konsumen**.

**Pendekatan yang dipilih**: `typing.Protocol`, dipecah jadi dua (`PlannerLLM` 3 method, `OrchestratorLLM` sebagai superset-nya).

**Alasan**: Protocol membuat `FakeLLMService` yang sudah ada di test valid tanpa diubah sama sekali (structural typing, bukan nominal). Dipecah jadi dua mengikuti Interface Segregation -- `run_plan()` tidak pernah butuh `classify_message`, jadi tidak boleh dipaksa mendeklarasikannya.

**Trade-off**: Ada dua Protocol untuk dijaga sinkron kalau kebutuhan method berubah (mis. kalau `run_plan` suatu saat butuh method baru, harus ditambah di `PlannerLLM`, otomatis ikut ke `OrchestratorLLM` lewat inheritance -- tapi kalau desainnya berubah, perlu diperhatikan manual).

---

## ADR-005: Single-User, Tanpa Autentikasi (untuk MVP)

**Keputusan**: Semua endpoint memakai `get_or_create_default_user()` -- satu user default untuk seluruh sistem, tidak ada login/autentikasi.

**Konteks**: Visi proyek adalah "AI personal" (satu pengguna), bukan produk multi-tenant.

**Opsi**:

- Bangun autentikasi penuh (JWT/session) sejak awal -- sesuai visi jangka panjang, tapi menambah kompleksitas signifikan untuk MVP yang belum butuh multi-user.
- Single default user -- MVP paling sederhana yang cukup untuk kebutuhan saat ini.

**Pendekatan yang dipilih**: Single default user.

**Alasan**: Menghindari abstraksi prematur (Bagian 20 & 31 di prompt awal proyek) -- auth belum dibutuhkan untuk kasus pemakaian personal single-user.

**Trade-off**: Kalau Thinker nanti perlu diakses multi-user (misalnya dipakai lebih dari satu orang, atau diekspos publik), ini titik yang butuh desain ulang menyeluruh: dependency `get_current_user`, isolasi data per user di level query (bukan cuma `user_id` sebagai kolom, tapi enforcement di setiap query), dan kemungkinan migrasi data existing.

---

## ADR-006: Strategi Testing -- Dua Level Terpisah (Unit + API), Bukan Integration Test Penuh

**Keputusan**: Test dibagi jadi unit test (service layer langsung, tanpa HTTP/DB) dan API test (`TestClient` FastAPI, `get_db_session` di-override dengan sesi palsu, service layer di-mock).

**Konteks**: Audit menemukan bug (`conversation_id=uuid.UUID`, salah tanda baca) yang lolos karena hanya ada unit test -- tidak ada satupun test yang benar-benar memanggil endpoint lewat FastAPI routing.

**Opsi**:

- **Cuma unit test** -- cepat, tapi tidak menguji routing/validasi HTTP/dependency injection sama sekali (persis bug yang lolos).
- **Integration test penuh** (database PostgreSQL sungguhan di test) -- paling realistis, tapi lambat, butuh setup Docker di CI, dan test jadi rapuh terhadap state DB.
- **API test dengan DB di-mock** -- menguji lapisan HTTP (routing, validasi Pydantic, status code) tanpa butuh database sungguhan.

**Pendekatan yang dipilih**: Unit test + API test dengan DB di-mock (bukan integration test penuh).

**Alasan**: Menutup celah yang menyebabkan bug lolos (tidak ada test HTTP-level sama sekali) dengan biaya kecepatan yang minimal -- 86 test jalan dalam < 1 detik karena tidak ada I/O sungguhan.

**Trade-off**: Tidak ada test yang benar-benar memverifikasi query SQLAlchemy terhadap PostgreSQL sungguhan (mis. constraint, tipe kolom `UUID(as_uuid=True)`, cascade delete). Bug di level SQL/ORM murni bisa saja masih lolos. Kalau proyek berkembang, lapisan ketiga (integration test dengan Postgres asli, mungkin lewat testcontainers) adalah kandidat penambahan berikutnya.

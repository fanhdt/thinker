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

---

## ADR-007: Structured JSON Logging, Bukan Format Teks Bebas

**Keputusan**: Semua log di seluruh codebase ditulis sebagai satu objek JSON per baris (`JsonFormatter` di `app/core/logging_config.py`), lewat satu helper `log_event(logger, "nama_event", **fields)` -- bukan `logger.info("teks bebas %s", x)`.

**Konteks**: Sistem sudah cukup agentic (planner, reflection, tool-calling) sehingga sulit didebug lewat log teks polos -- tidak bisa difilter/di-`jq` terstruktur, dan gampang inkonsisten format antar file (sempat ditemukan dua "dialek" log berbeda di codebase yang sama sebelum disatukan).

**Opsi**:

- Tetap `logging.basicConfig` format teks -- paling sederhana, tapi tidak bisa diquery terstruktur, dan riwayat proyek sempat ada bug logging (`exc.code in (429.503)` -- placeholder `%s` yang tidak pernah tersubstitusi) yang lolos karena log-nya "kelihatan ada" padahal salah.
- Logging library pihak ketiga (`structlog`, dst) -- lebih kaya fitur, tapi dependency baru untuk kebutuhan yang bisa dipenuhi stdlib.
- `logging.Formatter` kustom + helper `log_event()` tipis -- stdlib saja, satu titik format.

**Pendekatan yang dipilih**: `JsonFormatter` + `log_event()`, stdlib saja.

**Alasan**: Cukup untuk kebutuhan single-instance MVP ini (Bagian 21: "semakin agentic, semakin penting observability"), tanpa menambah dependency yang belum perlu.

**Trade-off**: Tidak ada agregasi/dashboard bawaan -- log JSON ini masih perlu dibaca manual atau lewat tool eksternal (`jq`, atau sistem log terpusat) kalau volume log membesar. Untuk single-user MVP ini belum jadi masalah nyata.

---

## ADR-008: Menggabungkan Panggilan LLM yang Berpasangan (`classify_and_plan`, `execute_and_evaluate`)

**Keputusan**: `classify_message` + `create_plan` digabung jadi satu panggilan `classify_and_plan`; `execute_task` + `evaluate_result` digabung jadi satu panggilan `execute_and_evaluate`.

**Konteks**: Free tier kebanyakan provider LLM (mis. Gemini free tier: 15 request/menit) gampang habis karena satu plan dengan N task butuh `1 (classify) + 1 (create_plan) + 2N (execute+evaluate per task)` panggilan -- plan 6 task saja sudah 14 panggilan, nyaris kena limit rate dalam satu kali proses pesan.

**Opsi**:

- Biarkan terpisah -- lebih mudah dinalar (satu panggilan = satu tanggung jawab), tapi boros panggilan.
- Gabungkan lewat structured output: minta LLM mengerjakan DUA hal sekaligus dalam satu response schema (mis. `MessagePlan{needs_planning, tasks}`, `TaskOutcome{result, is_correct, feedback}`).
- Rate-limit/backoff di level aplikasi tanpa mengurangi jumlah panggilan -- tidak mengurangi biaya, cuma menyebar waktu.

**Pendekatan yang dipilih**: Gabungkan lewat structured output.

**Alasan**: Mengurangi jumlah panggilan hingga ~50% (plan 6 task: 14 -> 7) tanpa kehilangan granularitas reflection loop per-task (`execute_and_evaluate` tetap dipanggil ulang per task per percobaan retry, bukan dibatch di akhir -- itu akan kehilangan kemampuan retry-dengan-feedback per task).

**Trade-off**: `execute_and_evaluate` menggabungkan `tools` (function-calling) DENGAN `response_schema` (structured output) dalam satu request -- kombinasi yang di beberapa provider/model bisa bermasalah (ditemukan issue nyata di ekosistem `google-genai`). Sudah diverifikasi jalan di produksi untuk Gemini 3 series dan OpenAI-compatible provider (OpenRouter, Groq), tapi bukan jaminan universal untuk semua model -- kalau kombinasi ini gagal di model/provider tertentu, akan kelihatan sebagai `llm_parse_failed`/`llm_empty_response` di log (lihat ADR-013), bukan gagal diam-diam.

---

## ADR-009: Model-Agnostic Architecture -- Boundary `LLMProvider`

**Keputusan**: Pisahkan logika bisnis LLM (`app/services/llm.py`: prompt, schema, alur reflection) dari detail provider (`app/services/llm_providers/`: bentuk request, cara tool-calling dijalankan, cara error dipetakan) lewat satu Protocol generik `LLMProvider`.

**Konteks**: Sebelum ini, `LLMService` satu kelas berisi campuran logika bisnis DAN pemanggilan `google.genai` langsung (`self._client.aio.models.generate_content(...)`, `types.GenerateContentConfig`, dst) -- mengganti provider berarti mengedit ulang tiap method satu-satu. Ini bertentangan langsung dengan Bagian 18 visi awal proyek: _"Thinker harus sebisa mungkin tidak bergantung pada satu provider... provider-specific implementation harus berada di boundary."_

**Opsi**:

- Biarkan `LLMService` terikat langsung ke Gemini SDK -- paling sederhana sekarang, tapi bertentangan dengan visi proyek dan makin mahal diubah makin lama dibiarkan.
- Abstraksi minimal: cuma pisahkan konstruksi client (`genai.Client(...)`) dari pemakaiannya -- tidak cukup, karena bentuk request (`response_schema`, `tools`) tetap Gemini-spesifik di tiap method.
- Boundary penuh: `LLMProvider` Protocol dengan `generate(messages, response_schema, use_tools) -> GenerationResult` generik, provider konkret (`GeminiProvider`, `OpenAICompatibleProvider`) menerjemahkan ke/dari bentuk provider masing-masing.

**Pendekatan yang dipilih**: Boundary penuh.

**Alasan**: `LLMService` sekarang betul-betul tidak pernah `import google.genai` atau `import openai` -- provider bisa diganti murni lewat config (lihat ADR-010, ADR-011, ADR-012), tanpa menyentuh satu baris pun di `llm.py`.

**Trade-off**: Lapisan abstraksi tambahan (dan Protocol lain lagi, `PlannerLLM`/`OrchestratorLLM` di ADR-004, yang sekarang berada DI ATAS boundary ini) -- dua lapis abstraksi LLM sekaligus bisa terasa berlebihan untuk yang belum familiar dengan codebase-nya. Tapi keduanya menjawab pertanyaan berbeda (lihat ARCHITECTURE.md §6) dan sudah terbukti perlu keduanya: §5 yang membuat 5 provider berbeda bisa dipakai tanpa mengubah kode, §6 yang membuat `planner_service`/`orchestrator_service` bisa ditest tanpa provider sungguhan sama sekali.

---

## ADR-010: Failover Otomatis Antar Provider (`FallbackProvider`)

**Keputusan**: `FallbackProvider` membungkus daftar `LLMProvider` dan mencoba berurutan sampai satu berhasil, dikonfigurasi lewat `LLM_PROVIDER_CHAIN` (dipisah koma).

**Konteks**: Dua insiden produksi nyata dalam sesi pengembangan yang sama: Gemini free tier kena rate limit (429) di tengah proses satu plan, dan saldo OpenRouter habis (402) -- keduanya menyebabkan seluruh pesan gagal total tanpa mekanisme pemulihan otomatis.

**Opsi**:

- Biarkan gagal, user kirim ulang manual -- pengalaman buruk, dan tidak memanfaatkan bahwa Thinker sudah mendukung banyak provider (ADR-009).
- Retry ke provider yang SAMA dengan backoff -- tidak membantu kalau penyebabnya kuota/saldo habis (menunggu tidak mengubah keadaan itu dalam skala menit).
- Failover ke provider LAIN dalam rantai yang dikonfigurasi -- provider berbeda biasanya punya kuota/kondisi independen.

**Pendekatan yang dipilih**: Failover ke provider lain, `FallbackProvider`.

**Alasan**: Langsung mengatasi kedua insiden nyata tanpa perlu campur tangan user; tiap provider di rantai biasanya punya kuota/billing independen jadi kegagalan satu tidak berkorelasi dengan yang lain.

**Trade-off**: `FallbackProvider` sengaja memperlakukan SEMUA `ProviderError` sebagai alasan pindah provider, termasuk yang non-retryable (mis. nama model salah) -- ini pilihan sadar (lihat ARCHITECTURE.md §7 untuk alasannya), tapi berarti kesalahan konfigurasi di provider pertama (mis. model 404 karena typo) akan "tersembunyi" oleh keberhasilan provider berikutnya alih-alih gagal keras dan ketahuan segera. Mitigasinya: event `provider_fallback` selalu di-log tiap kali ini terjadi (lihat ADR-007), jadi kesalahan konfigurasi tetap terlihat di log walau request-nya sendiri tetap berhasil.

---

## ADR-011: Multi-Key per Provider Lewat Satu Field, Dipisah Koma

**Keputusan**: Field `*_API_KEY` (mis. `GEMINI_API_KEY`) boleh diisi lebih dari satu key dipisah koma; tiap key otomatis jadi instance provider terpisah dalam rantai failover (ADR-010).

**Konteks**: Kebutuhan nyata: beberapa project Gemini gratis berbeda (tiap project kuotanya independen) sebagai lapisan resiliency tambahan sebelum benar-benar pindah provider.

**Opsi**:

- Field config baru per key tambahan (`GEMINI_API_KEY_2`, `GEMINI_API_KEY_3`, dst) -- eksplisit tapi tidak terbatas (butuh field baru tiap nambah key), dan tidak konsisten dengan pola `LLM_PROVIDER_CHAIN` yang sudah dipisah koma.
- Field terpisah berisi list -- butuh parsing config array, lebih rumit untuk `.env` (yang secara native cuma string).
- Reuse field yang sudah ada, dipisah koma, sama seperti `LLM_PROVIDER_CHAIN` -- konsisten, tidak nambah field config baru sama sekali.

**Pendekatan yang dipilih**: Reuse field yang sudah ada, dipisah koma.

**Alasan**: Nol field config baru, pola yang sama (dipisah koma) sudah dikenal user dari `LLM_PROVIDER_CHAIN`, dan bisa dikombinasikan otomatis (`LLM_PROVIDER_CHAIN=gemini,openrouter` + `GEMINI_API_KEY=key1,key2` = 3 instance, bukan 2 -- lihat ARCHITECTURE.md §8).

**Trade-off**: Kalau suatu saat sebuah API key sungguhan mengandung karakter koma (tidak lazim tapi bukan mustahil untuk beberapa provider), ini akan salah diparse jadi 2 key. Belum jadi masalah nyata untuk provider yang didukung saat ini.

---

## ADR-012: Tiering Provider -- Simple vs Planner

**Keputusan**: `LLMService` punya provider terpisah untuk task "simple" (`chat`, `chat_with_history`, `extract_fact`, `classify_and_plan`) dan task "planner" (`create_plan`, `execute_and_evaluate`), dikonfigurasi lewat `LLM_PROVIDER_SIMPLE`/`LLM_PROVIDER_PLANNER`.

**Konteks**: `ARCHITECTURE.md` sempat eksplisit mencatat ini sebagai keterbatasan terbuka ("belum ada cost control / model routing... satu model dipakai untuk semua tugas"). Task planner (reasoning + tool-calling) jauh lebih berat/mahal dari sekadar keputusan routing atau chat biasa.

**Opsi**:

- Satu model untuk semua tugas -- sederhana, tapi boros untuk task ringan yang sebenarnya tidak butuh model kuat/mahal.
- Heuristik otomatis pilih model berdasar kompleksitas pesan -- butuh langkah klasifikasi tambahan (panggilan LLM ekstra) untuk memutuskan, bertentangan dengan tujuan (ADR-008) mengurangi panggilan.
- Pembagian tier eksplisit di config (simple vs planner), ditentukan developer, bukan runtime heuristic -- lebih sederhana, dan pembagian method mana masuk tier mana sudah jelas dari tanggung jawabnya masing-masing.

**Pendekatan yang dipilih**: Pembagian tier eksplisit di config.

**Alasan**: `classify_and_plan` dipanggil di SETIAP pesan (routing decision) -- harus tetap tier simple walau dia juga menyusun task, supaya biaya per-pesan tetap rendah; `execute_and_evaluate` yang benar-benar melakukan pekerjaan berat dapat model yang lebih kuat.

**Trade-off**: Kalau tidak dikonfigurasi sama sekali, kedua tier jatuh ke provider default yang sama (`build_provider()`) -- desain sengaja backward-compatible, tapi berarti manfaat tiering baru terasa kalau user benar-benar mengisi `LLM_PROVIDER_SIMPLE`/`LLM_PROVIDER_PLANNER` secara eksplisit.

---

## ADR-013: Kegagalan Task Planner -- `is_correct=False`, Bukan Exception Fatal

**Keputusan**: Kalau `execute_and_evaluate` tidak menghasilkan jawaban sama sekali (mis. LLM kehabisan jatah tool-call sebelum sempat menjawab), itu diperlakukan sebagai `is_correct=False` (masuk reflection retry loop yang sudah ada, ADR lihat ARCHITECTURE.md §4) -- BUKAN `raise LLMServiceError` seperti sebelumnya.

**Konteks**: Insiden produksi nyata -- satu task butuh banyak `web_search` berturut-turut, mentok di batas jumlah pemanggilan tool (`MAX_TOOL_CALLS_PER_REQUEST`), dan Gemini mengembalikan respons tanpa teks sama sekali. Perilaku lama (`raise LLMServiceError("hasil kosong")`) tidak tertangkap di mana pun sampai ke `message_pipeline`, MENGGAGALKAN SELURUH pesan -- padahal cuma satu dari beberapa task di plan yang bermasalah.

**Opsi**:

- Biarkan `raise` seperti sebelumnya -- konsisten dengan gaya "gagal keras kalau data tidak masuk akal", tapi terbukti terlalu agresif untuk kasus ini: satu task gagal menjatuhkan keseluruhan percakapan.
- Tangkap exception di `planner_service` dan lanjutkan ke task berikutnya -- menutupi gejala di tempat yang salah (jauh dari sumber masalah), dan reflection loop yang sudah ada jadi tidak terpakai untuk kasus ini.
- Ubah jadi `is_correct=False` di sumbernya (`llm.py`) -- reflection loop yang SUDAH ADA otomatis menangani retry-dengan-feedback, task lain di plan tetap lanjut walau satu task akhirnya gagal total setelah semua percobaan habis.

**Pendekatan yang dipilih**: Ubah jadi `is_correct=False` di sumbernya.

**Alasan**: Memakai mekanisme yang sudah ada dan sudah teruji (bounded reflection loop) alih-alih menambah penanganan error baru di tempat lain; kegagalan lokal ke satu task tidak lagi berarti kegagalan seluruh pesan.

**Trade-off**: Menaikkan `MAX_TOOL_CALLS_PER_REQUEST` (5 -> 8) sebagai mitigasi tambahan mengurangi frekuensi kejadian ini, tapi tidak menghilangkannya -- task yang genuinely butuh lebih dari 8 pemanggilan tool berturut-turut akan tetap kena kasus ini, cuma sekarang gagalnya graceful (retry lalu "belum sempurna" kalau tetap gagal) alih-alih fatal.

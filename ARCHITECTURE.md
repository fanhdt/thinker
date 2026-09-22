# Arsitektur Thinker

## 1. Struktur Layer

```
backend/app/
├── api/              <- FastAPI routes. Terima HTTP request, validasi lewat Pydantic,
│                        panggil service, kembalikan response. TIDAK ada business logic di sini
│                        kecuali validasi input yang murni soal HTTP (mis. tipe file, ukuran file).
├── services/         <- Business logic. Tidak tahu apa-apa soal HTTP/FastAPI.
│   └── llm_providers/  <- Boundary provider LLM (Gemini/OpenAI/Groq/DeepSeek/OpenRouter). Lihat §5.
├── models/           <- SQLAlchemy ORM (representasi tabel database).
├── schemas/          <- Pydantic (bentuk request/response HTTP, terpisah dari model DB).
├── db/               <- Setup koneksi database (engine, session factory).
├── telegram/         <- Bot Telegram, memakai pipeline yang sama dengan REST API.
└── core/             <- Konfigurasi (env vars), structured logging, observability helper.
```

Alasan `schemas/` terpisah dari `models/`: model DB dan bentuk API punya alasan berubah yang berbeda (separation of concerns). Menambah kolom internal ke `Memory` model tidak harus otomatis mengubah apa yang diekspos lewat `MemoryOut`.

## 2. Alur `POST /conversations/{id}/messages` (rute paling kompleks)

Ini rute yang menyatukan hampir semua subsistem Thinker:

```
Request masuk
  │
  ├─ Validasi conversation_id (path) & message (body, min_length=1)
  ├─ conversation_service.get_conversation() -- 404 kalau tidak ada
  ├─ conversation_service.add_message(role="user")
  │
  ├─ Kumpulkan konteks (best-effort, TIDAK saling menggagalkan):
  │    ├─ memory_service.retrieve_relevant_memories()   -- embed_query lalu cosine similarity
  │    ├─ document_service.retrieve_relevant_chunks()   -- RAG atas dokumen yang diupload
  │    └─ goal_service.get_goals() + personalization_service -- goals & preferensi user
  │
  ├─ orchestrator_service.handle_message(llm, message, history, context_text)
  │    │
  │    ├─ llm.classify_and_plan(message) -- SATU panggilan: butuh planner? kalau ya, sekalian
  │    │    dapat daftar task-nya (dulu ini 2 panggilan terpisah: classify_message + create_plan)
  │    │
  │    ├─ [needs_planning=False] -> llm.chat_with_history() -- satu balasan langsung
  │    │
  │    └─ [needs_planning=True]  -> planner_service.run_plan(llm, message, plan=<dari atas>)
  │           └─ untuk tiap task: _execute_task_with_reflection()
  │                  ├─ llm.execute_and_evaluate() -- SATU panggilan: kerjakan + nilai sendiri
  │                  │    (dulu ini 2 panggilan terpisah: execute_task + evaluate_result)
  │                  └─ kalau tidak lulus: retry dengan feedback, MAKSIMAL 2x (bounded loop)
  │
  ├─ conversation_service.add_message(role="assistant", orchestrated.reply)
  │
  └─ Ekstraksi memori (best-effort, tidak menggagalkan response kalau gagal):
       ├─ llm.extract_fact(message, existing_memories) -- LLM menilai operation: CREATE/UPDATE/DELETE/IGNORE
       ├─ CREATE: embed_document() lalu store_memory_if_new()
       ├─ UPDATE/DELETE: target_index divalidasi dulu terhadap daftar existing_memories yang dikirim
       └─ IGNORE, atau embedding gagal: dilewati saja, response tetap terkirim
```

**Prinsip penting di alur ini**: retrieval memori/RAG dan ekstraksi memori itu _best-effort_ -- kalau LLM sedang bermasalah di titik itu, chat tetap harus jalan (`except LLMServiceError: log warning, lanjut tanpa context`). Cuma jalur inti (`orchestrator_service.handle_message`) yang boleh menggagalkan seluruh request (503 atau 429, lihat §11).

## 3. Routing Simple vs Complex (`classify_and_plan`)

Thinker tidak selalu memakai planner. Sebelum menjawab, LLM sendiri diminta menilai apakah pesan butuh "rencana bertahap" (`needs_planning=true`) atau cukup satu balasan chat (`needs_planning=false`) -- dan kalau ya, sekaligus memecahnya jadi daftar task dalam **satu** panggilan yang sama (`classify_and_plan`). Ini menghindari agent loop yang tidak perlu untuk permintaan sederhana, sekaligus menghindari panggilan LLM ganda untuk keputusan yang sebenarnya bisa dijawab sekali jalan.

Method ini sengaja jalan di tier "simple" (lihat §9), bukan tier "planner", walau dia juga menyusun task -- karena dipanggil di **setiap** pesan user (bukan cuma yang butuh planning), jadi harus tetap murah/cepat. Kualitas pemecahan task tidak sekritis itu di sini karena pekerjaan berat sesungguhnya ada di `execute_and_evaluate`.

## 4. Reflection Loop yang Dibatasi

`planner_service._execute_task_with_reflection()` mengeksekusi satu task DAN meminta LLM mengevaluasi hasilnya sendiri dalam satu panggilan (`execute_and_evaluate`), dan kalau dinilai belum benar, mencoba ulang dengan feedback dari evaluasi sebelumnya. Jumlah percobaan dibatasi `MAX_REFLECTION_ATTEMPTS = 2` -- ini bukan angka sembarang, tapi keputusan sadar supaya loop **selalu berhenti**, tidak peduli seberapa buruk hasilnya (dibuktikan lewat test `test_reflection_loop_is_bounded_even_when_always_wrong`).

Kalau LLM tidak menghasilkan jawaban sama sekali (mis. kehabisan jatah tool-call sebelum sempat menjawab -- lihat §8), itu diperlakukan sebagai `is_correct=False` (masuk siklus retry di atas), **bukan** exception yang menjatuhkan seluruh pipeline pesan. Task lain di plan yang sama tetap lanjut dikerjakan walau satu task gagal total setelah semua percobaan habis (ditandai "belum sempurna" di summary, bukan membatalkan seluruh plan).

## 5. Model-Agnostic Architecture: `LLMProvider`

Semua logika bisnis LLM (`app/services/llm.py`) TIDAK PERNAH mengetahui provider mana yang sebenarnya dipakai. Batasannya ada di `app/services/llm_providers/`:

```
app/services/llm_providers/
├── base.py                <- Protocol `LLMProvider` + tipe generik (GenerationResult,
│                              TokenUsage, ProviderError). Nol kosakata provider spesifik.
├── gemini.py               <- GeminiProvider -- satu-satunya file yang boleh import google.genai
├── openai_compatible.py    <- OpenAICompatibleProvider -- SATU kelas untuk OpenAI, Groq,
│                              DeepSeek, DAN OpenRouter (beda cuma base_url/api_key/model)
├── fallback.py             <- FallbackProvider -- rantai failover antar provider (§7)
├── tool_schema.py          <- konversi fungsi Python (AVAILABLE_TOOLS) -> JSON schema
│                              gaya OpenAI function-calling
└── factory.py              <- satu-satunya tempat yang menerjemahkan config -> provider konkret
```

`LLMService.__init__` menerima `simple_provider`/`planner_provider` (atau `provider` tunggal untuk backward-compat/test), dibangun lewat `factory.build_simple_provider()`/`build_planner_provider()` kalau tidak disuntik manual. Tiap method bisnis (`chat`, `classify_and_plan`, `execute_and_evaluate`, dst) memanggil `self._provider.generate(messages, response_schema=..., use_tools=...)` -- request generik, bukan bentuk request Gemini/OpenAI spesifik.

Kenapa `OpenAICompatibleProvider` satu kelas untuk 4 provider (bukan 4 kelas terpisah): OpenAI, Groq, DeepSeek, dan OpenRouter semuanya benar-benar kompatibel dengan format API OpenAI (`base_url` berbeda, request/response sama) -- menambah provider OpenAI-compatible baru cukup satu cabang `if` baru di `factory.py`, bukan kelas baru.

`GeminiProvider` beda sendiri karena SDK-nya (`google-genai`) tidak kompatibel format OpenAI, dan punya kemampuan yang tidak ada di OpenAI-compatible API secara native: automatic function calling (SDK menjalankan Python callable langsung tanpa loop manual). `OpenAICompatibleProvider` mengimplementasikan loop tool-calling manual sendiri (lihat `tool_schema.py` + `_run_tool` di `openai_compatible.py`) untuk menyamai kemampuan itu.

## 6. Abstraksi Protocol Layer Bisnis: `PlannerLLM` & `OrchestratorLLM`

Terpisah dari `LLMProvider` (§5, boundary provider mentah), ada satu lapisan abstraksi lagi di `app/services/llm_provider.py` -- `typing.Protocol` yang dipakai `planner_service` dan `orchestrator_service` supaya mereka tidak bergantung pada `LLMService` yang konkret:

```
PlannerLLM (Protocol)        -- create_plan, execute_and_evaluate
    ↑
OrchestratorLLM (Protocol)   -- + classify_and_plan, chat_with_history
```

Ini **dependency inversion** di layer yang berbeda dari §5: §5 memisahkan `LLMService` dari provider konkret (Gemini vs OpenAI dsb), §6 memisahkan `planner_service`/`orchestrator_service` dari `LLMService` itu sendiri. Keduanya perlu ada bersamaan -- kalau cuma §5 yang ada, `planner_service` tetap terikat ke `LLMService` sebagai satu-satunya implementasi; kalau cuma §6 yang ada, `LLMService` tetap terikat langsung ke Gemini SDK.

Kenapa dua Protocol terpisah, bukan satu besar berisi semua method `LLMService`: **Interface Segregation** -- `run_plan()` tidak pernah butuh `classify_and_plan`, jadi tidak dipaksa mendeklarasikannya. Ini juga membuat test double (`FakeLLMService` di test) valid secara struktural tanpa perlu mengimplementasikan method yang tidak pernah dipakai.

Di API layer (`conversations.py`, `planner.py`) -- composition root, tempat instance `LLMService` sungguhan dirakit -- tetap memakai tipe konkret `LLMService`. Ini bukan pengecualian yang tidak konsisten: composition root memang seharusnya tahu tipe konkret; yang tidak boleh adalah _business logic_ yang bergantung padanya.

## 7. Failover Otomatis Antar Provider: `FallbackProvider`

`FallbackProvider` (di `llm_providers/fallback.py`) membungkus daftar `LLMProvider` dan mencoba tiap satu berurutan sampai ada yang berhasil. **Ini bukan retry** (mengulang request yang sama ke provider yang sama) -- itu urusan `retryable` flag di `ProviderError` dan pemanggil di layer atas. `FallbackProvider` murni "kalau provider ini bermasalah, pindah ke yang lain", jadi SEMUA `ProviderError` jadi alasan pindah, termasuk yang non-retryable (mis. nama model salah/404) -- karena bagi failover, itu tetap berarti "provider ini tidak bisa dipakai sekarang", terlepas dari apakah mengulang ke provider yang SAMA akan membantu.

Dikonfigurasi lewat `LLM_PROVIDER_CHAIN` (dan turunannya per-tier, `LLM_PROVIDER_SIMPLE_CHAIN`/`LLM_PROVIDER_PLANNER_CHAIN`), dipisah koma: `gemini,openrouter,groq,deepseek`. `factory.py` juga otomatis membungkus dalam `FallbackProvider` kalau satu provider punya lebih dari satu API key (lihat §8) -- bahkan tanpa `*_CHAIN` diisi sama sekali.

## 8. Multi-Key per Provider

Field `*_API_KEY` mana pun (`GEMINI_API_KEY`, dst) boleh diisi lebih dari satu key dipisah koma: `GEMINI_API_KEY=key-project-1,key-project-2`. `factory._build_provider_instances()` memecahnya jadi satu instance provider per key, lalu `_build_from_config()` membungkusnya dalam `FallbackProvider` (kecuali cuma 1 key -- tidak dibungkus, supaya kasus paling umum tidak dapat lapisan tak perlu). Ini kombinasi natural dengan §7: `LLM_PROVIDER_CHAIN=gemini,openrouter` dengan `GEMINI_API_KEY=key1,key2` menghasilkan rantai 3 instance (gemini-key1, gemini-key2, openrouter), bukan 2.

Kasus pemakaian utama: beberapa project Gemini gratis berbeda (kuota per-project), dicoba bergantian sebelum benar-benar pindah ke provider lain.

## 9. Tiering: Provider Berbeda untuk Task Ringan vs Task Planner

`LLMService` punya dua provider terpisah: `_simple_provider` (dipakai `chat`, `chat_with_history`, `extract_fact`, `classify_and_plan` -- dipanggil di tiap pesan, harus murah/cepat) dan `_planner_provider` (dipakai `create_plan`, `execute_and_evaluate` -- reasoning paling berat, kadang pakai tools). Dikonfigurasi lewat `LLM_PROVIDER_SIMPLE`/`LLM_PROVIDER_PLANNER` (atau varian `*_CHAIN`-nya masing-masing untuk failover per-tier).

Kalau tidak dikonfigurasi sama sekali, kedua tier jatuh ke `LLM_PROVIDER`/`LLM_PROVIDER_CHAIN` yang sama (`factory.build_simple_provider()`/`build_planner_provider()` fallback ke `build_provider()`) -- jadi tidak mengonfigurasi tiering sama sekali = perilaku identik dengan sebelum tiering ada, tidak ada breaking change.

## 10. Observability: Structured Logging

Semua log tertulis sebagai satu objek JSON per baris (`app/core/logging_config.py`, `JsonFormatter`), bukan teks bebas -- supaya bisa di-`jq`/filter terstruktur. Helper `log_event(logger, "nama_event", **fields)` adalah SATU-SATUNYA cara menulis event terstruktur di seluruh codebase (bukan `logger.info("op=%s ...", ...)` format string manual) -- dipakai konsisten dari `llm_call` (di provider layer) sampai `pipeline_summary` (di message_pipeline).

Tiap request HTTP dapat `request_id` (middleware di `main.py`, contextvar di `logging_config.py`) yang otomatis ikut ke semua log dalam request itu -- satu alur penuh (dari terima pesan sampai balasan terkirim) bisa ditelusuri lewat satu id yang sama. Jalur Telegram bot tidak lewat HTTP middleware ini, jadi `request_id`-nya selalu `"-"` di log jalur itu (bukan bug -- itu memang di luar konteks request FastAPI).

Event kunci yang di-log: `llm_call` (method/provider/model, durasi, sukses/gagal, token usage, tools_called), `llm_parse_failed`/`llm_empty_response` (diagnostik kalau structured output gagal di-parse atau kosong -- termasuk isi mentah respons untuk didebug), `memory_retrieval`/`document_retrieval` (jumlah kandidat vs yang dikembalikan), `task_execution_finished`/`reflection_retry`/`plan_execution_finished`, `message_handled`/`planner_decision`, `provider_fallback`/`provider_fallback_succeeded` (§7), `pipeline_summary`.

## 11. Reliability: Penanganan Error LLM

`ProviderError.retryable` (diset oleh tiap provider berdasarkan kode error -- 429/503 untuk Gemini, status code dari `openai.APIError` untuk yang OpenAI-compatible) diteruskan apa adanya ke `LLMServiceError.retryable`, lalu ke HTTP layer:

- `retryable=True` -> HTTP **429** + pesan "Layanan AI sedang dibatasi (rate limit). Coba lagi dalam beberapa saat." (bukan 503 generik dengan teks error mentah dari provider)
- `retryable=False` -> HTTP **503** + pesan error asli

Bot Telegram membedakan pesan yang sama: retryable -> "Lagi kena limit dari layanan AI-nya... coba lagi dalam 1 menit", non-retryable -> pesan generik "ada gangguan sementara".

Kegagalan SEBAGIAN (satu task di plan yang tidak menghasilkan jawaban -- lihat §4) tidak menjatuhkan seluruh request; hanya exception yang benar-benar tidak tertangani (provider gagal total setelah melewati seluruh rantai failover) yang sampai ke HTTP layer sebagai 429/503.

## 12. Validasi Respons Terstruktur dari LLM

`GenerationResult.parsed` dari provider bertipe generik (bisa `None` kalau provider gagal mengikuti `response_schema` yang diminta) -- tiap provider (`GeminiProvider`, `OpenAICompatibleProvider`) memvalidasi dengan `isinstance()` sebelum menaruh sesuatu di situ, TIDAK PERNAH mengklaim tipe tanpa validasi runtime. `llm.py` selalu mengecek `isinstance(outcome.parsed, <SchemaClass>)` lagi di sisi bisnis sebelum memakainya. Tiap titik punya perilaku fallback berbeda kalau validasi gagal:

| Fungsi                 | Kalau parsing gagal / respons tidak sesuai                                                                                                                                                                                                     |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_plan`          | `raise LLMServiceError` -- planning eksplisit diminta user (endpoint `/conversations/{id}/plan`), wajar gagal keras                                                                                                                            |
| `classify_and_plan`    | fallback `needs_planning=False, tasks=[]` -- anggap simple task, konsisten dengan fallback API error di atasnya                                                                                                                                |
| `execute_and_evaluate` | ada teks tapi parsing gagal -> fallback `is_correct=True` (fail-open); TIDAK ADA teks sama sekali -> `is_correct=False` (masuk retry loop, lihat §4); hasil kosong tapi ditandai `is_correct=True` -> diturunkan paksa jadi `is_correct=False` |
| `extract_fact`         | fallback `None` (+ log warning) -- anggap tidak ada perubahan memori                                                                                                                                                                           |

## 13. Sistem Memori

Retrieval memori memakai kombinasi _similarity_ (cosine similarity antara embedding query dan embedding memori) dan _importance_ (skor 1-5 yang ditentukan LLM saat ekstraksi):

```python
final_score = (0.7 * similarity) + (0.4 * (importance / 5))
```

Ini sengaja bukan cuma similarity murni -- memori yang sangat penting (importance tinggi) bisa mengalahkan memori yang sedikit lebih mirip tapi kurang penting (dibuktikan lewat `test_high_importance_can_outrank_slightly_higher_similarity`). Deduplikasi memakai threshold cosine similarity terpisah (`DEDUP_THRESHOLD = 0.92`) -- memori baru yang hampir identik dengan yang sudah ada tidak disimpan ulang.

Ekstraksi memori (`llm.extract_fact`) bukan cuma CREATE -- LLM diminta menentukan satu dari empat `operation`: CREATE (fakta baru), UPDATE (mengganti memori yang sudah ada, butuh `target_index` valid), DELETE (user eksplisit minta dilupakan, butuh `target_index` valid), atau IGNORE. `target_index` divalidasi terhadap panjang daftar `existing_memories` yang benar-benar dikirim ke prompt -- kalau LLM mengembalikan index di luar jangkauan, diperlakukan sebagai IGNORE (bukan crash atau UPDATE/DELETE ke memori yang salah).

## 14. Strategi Testing

Dua level, disengaja terpisah:

- **Unit test** (`test_planner_service.py`, `test_memory_service.py`, `test_gemini_provider.py`, `test_fallback_provider.py`, dst) -- memanggil fungsi service/provider langsung, pakai fake duck-typed (`FakeLLMService`, `FakeProvider`), tanpa FastAPI/HTTP/DB sama sekali. Cepat, fokus ke logika bisnis.
- **API test** (`test_conversations_api.py`, `test_goals_api.py`, dst) -- lewat `TestClient` FastAPI sungguhan, `get_db_session` di-override dengan sesi palsu (`conftest.py`), dan fungsi service-layer di-mock lewat `unittest.mock.patch`. Ini menguji hal yang tidak bisa dicek unit test: routing, validasi Pydantic di level HTTP, status code, dependency injection.

Kedua level ini dibutuhkan berbarengan -- riwayat proyek ini sempat punya bug (`conversation_id=uuid.UUID` yang salah tanda baca) yang lolos dari unit test karena unit test tidak pernah lewat FastAPI routing sama sekali.

Fixture yang memutasi state global (`settings`, khususnya konfigurasi provider LLM di `test_llm_provider_factory.py`) HARUS didefinisikan sekali di `tests/conftest.py` (autouse, global) -- bukan didefinisikan ulang secara lokal per file test. Fixture lokal cuma melindungi test-test di file itu sendiri; kalau ada file test lain yang memutasi `settings` yang sama tanpa fixture serupa, mutasinya bisa bocor ke test lain walau masing-masing file "kelihatannya" benar sendiri-sendiri.

## 15. Keterbatasan yang Diketahui (Bukan Bug)

- **Single-user**: tidak ada autentikasi. Semua endpoint memakai `get_or_create_default_user()` -- satu user default untuk seluruh sistem. Ini keputusan sadar untuk MVP personal, bukan kelalaian. Kalau Thinker perlu multi-user, ini titik yang perlu didesain ulang (auth, `get_current_user` dependency, isolasi data per user).
- **`EmbeddingService` masih Gemini-only**: model-agnostic architecture (§5-§9) mencakup chat/planner, TAPI TIDAK mencakup embedding (dipakai memory/document retrieval) -- itu masih terikat langsung ke `gemini-embedding-001`. Alasan: pgvector schema di database terikat ke dimensi 768 dari model itu; ganti provider embedding butuh migrasi skema, bukan cuma config. `GEMINI_API_KEY` karena itu tetap wajib diisi valid apa pun `LLM_PROVIDER` yang dipilih untuk chat/planner.
- **`OpenAICompatibleProvider` belum diverifikasi penuh di semua provider**: sudah terbukti jalan di produksi untuk OpenRouter dan Groq (termasuk tool-calling + structured output sekaligus), tapi belum ada verifikasi langsung untuk OpenAI asli dan DeepSeek -- kemungkinan ada perbedaan perilaku kecil (mis. dukungan tool-calling + JSON mode bersamaan) yang cuma akan kelihatan saat benar-benar dipakai.
- **Belum ada frontend**: Vue 3 + TypeScript + Tailwind yang direncanakan di awal proyek belum diimplementasikan sama sekali. Semua interaksi masih lewat REST API atau bot Telegram.

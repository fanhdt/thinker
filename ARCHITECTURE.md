# Arsitektur Thinker

## 1. Struktur Layer

```
backend/app/
├── api/          <- FastAPI routes. Terima HTTP request, validasi lewat Pydantic,
│                    panggil service, kembalikan response. TIDAK ada business logic di sini
│                    kecuali validasi input yang murni soal HTTP (mis. tipe file, ukuran file).
├── services/     <- Business logic. Tidak tahu apa-apa soal HTTP/FastAPI.
├── models/       <- SQLAlchemy ORM (representasi tabel database).
├── schemas/      <- Pydantic (bentuk request/response HTTP, terpisah dari model DB).
├── db/           <- Setup koneksi database (engine, session factory).
└── core/         <- Konfigurasi (env vars) dan setup logging.
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
  │    ├─ llm.classify_message() -- LLM menilai: butuh planner atau cukup chat biasa?
  │    │
  │    ├─ [needs_planning=False] -> llm.chat_with_history() -- satu balasan langsung
  │    │
  │    └─ [needs_planning=True]  -> planner_service.run_plan()
  │           ├─ llm.create_plan(goal) -> daftar task
  │           └─ untuk tiap task: _execute_task_with_reflection()
  │                  ├─ llm.execute_task()
  │                  ├─ llm.evaluate_result() -- lulus?
  │                  └─ kalau tidak lulus: retry dengan feedback, MAKSIMAL 2x (bounded loop)
  │
  ├─ conversation_service.add_message(role="assistant", orchestrated.reply)
  │
  └─ Ekstraksi memori (best-effort, tidak menggagalkan response kalau gagal):
       ├─ llm.extract_fact(message) -- LLM menilai: ada fakta baru yang layak diingat?
       ├─ kalau ada (extraction.fact tidak None): embed_document() lalu store_memory_if_new()
       └─ kalau tidak ada, atau embedding gagal: dilewati saja, response tetap terkirim
```

**Prinsip penting di alur ini**: retrieval memori/RAG dan ekstraksi memori itu _best-effort_ -- kalau Gemini API sedang bermasalah di titik itu, chat tetap harus jalan (`except LLMServiceError: log warning, lanjut tanpa context`). Cuma jalur inti (`orchestrator_service.handle_message`) yang boleh menggagalkan seluruh request (503).

## 3. Routing Simple vs Complex (`classify_message`)

Thinker tidak selalu memakai planner. Sebelum menjawab, LLM sendiri diminta menilai apakah pesan butuh "rencana bertahap" (`needs_planning=true`) atau cukup satu balasan chat (`needs_planning=false`). Ini menghindari agent loop yang tidak perlu untuk permintaan sederhana -- konsisten dengan prinsip "hindari penalaran kompleks untuk tugas sepele" yang jadi acuan proyek ini sejak awal.

## 4. Reflection Loop yang Dibatasi

`planner_service._execute_task_with_reflection()` mengeksekusi satu task, minta LLM mengevaluasi hasilnya (`evaluate_result`), dan kalau dinilai belum benar, mencoba ulang dengan feedback dari evaluasi sebelumnya. Jumlah percobaan dibatasi `MAX_REFLECTION_ATTEMPTS = 2` -- ini bukan angka sembarang, tapi keputusan sadar supaya loop **selalu berhenti**, tidak peduli seberapa buruk hasilnya (dibuktikan lewat test `test_reflection_loop_is_bounded_even_when_always_wrong`).

## 5. Abstraksi LLM: `PlannerLLM` & `OrchestratorLLM` (Protocol)

`planner_service` dan `orchestrator_service` (business logic inti) tidak bergantung pada `LLMService` yang konkret (yang terikat langsung ke Gemini SDK). Mereka bergantung pada `typing.Protocol` di `app/services/llm_provider.py`:

```
PlannerLLM (Protocol)        -- create_plan, execute_task, evaluate_result
    ↑
OrchestratorLLM (Protocol)   -- + classify_message, chat_with_history
```

Ini menegakkan **dependency inversion**: kalau suatu saat Thinker ingin ganti/tambah provider (OpenAI, Anthropic, model lokal), `planner_service` dan `orchestrator_service` tidak perlu diubah sama sekali -- cukup buat class baru yang mengimplementasikan Protocol yang sama.

Kenapa dua Protocol terpisah, bukan satu besar berisi semua method `LLMService`: **Interface Segregation** -- `run_plan()` tidak pernah butuh `classify_message`, jadi tidak dipaksa mendeklarasikannya. Ini juga membuat test double (`FakeLLMService` di test) valid secara struktural tanpa perlu mengimplementasikan method yang tidak pernah dipakai.

Di API layer (`conversations.py`, `planner.py`) -- composition root, tempat instance `LLMService` sungguhan dirakit -- tetap memakai tipe konkret `LLMService`. Ini bukan pengecualian yang tidak konsisten: composition root memang seharusnya tahu tipe konkret; yang tidak boleh adalah _business logic_ yang bergantung padanya.

## 6. Validasi Respons Terstruktur dari LLM

`response.parsed` dari SDK Gemini bertipe generik (`BaseModel | dict | Enum | None`) karena SDK tidak tahu skema spesifik yang kita minta. `llm.py` punya helper `_as_structured(response, model_cls)` yang memvalidasi dengan `isinstance()` di satu tempat, dipakai di keempat titik yang meminta output terstruktur (`extract_fact`, `create_plan`, `evaluate_result`, `classify_message`). Tiap titik punya perilaku fallback berbeda kalau validasi gagal:

| Fungsi             | Kalau parsing gagal                                                                    |
| ------------------ | -------------------------------------------------------------------------------------- |
| `create_plan`      | `raise LLMServiceError` -- planning adalah inti permintaan, wajar gagal keras          |
| `evaluate_result`  | fallback `is_correct=True` -- fail-open, cegah retry loop tak perlu                    |
| `classify_message` | fallback `False` -- anggap simple task, konsisten dengan fallback API error di atasnya |
| `extract_fact`     | fallback `None` (+ log warning) -- anggap tidak ada memori baru                        |

## 7. Sistem Memori

Retrieval memori memakai kombinasi _similarity_ (cosine similarity antara embedding query dan embedding memori) dan _importance_ (skor 1-5 yang ditentukan LLM saat ekstraksi):

```python
final_score = (0.7 * similarity) + (0.4 * (importance / 5))
```

Ini sengaja bukan cuma similarity murni -- memori yang sangat penting (importance tinggi) bisa mengalahkan memori yang sedikit lebih mirip tapi kurang penting (dibuktikan lewat `test_high_importance_can_outrank_slightly_higher_similarity`). Deduplikasi memakai threshold cosine similarity terpisah (`DEDUP_THRESHOLD = 0.92`) -- memori baru yang hampir identik dengan yang sudah ada tidak disimpan ulang.

## 8. Strategi Testing

Dua level, disengaja terpisah:

- **Unit test** (`test_planner_service.py`, `test_memory_service.py`, dst) -- memanggil fungsi service langsung, pakai `FakeLLMService` duck-typed, tanpa FastAPI/HTTP/DB sama sekali. Cepat, fokus ke logika bisnis.
- **API test** (`test_conversations_api.py`, `test_goals_api.py`, dst) -- lewat `TestClient` FastAPI sungguhan, `get_db_session` di-override dengan sesi palsu (`conftest.py`), dan fungsi service-layer di-mock lewat `unittest.mock.patch`. Ini menguji hal yang tidak bisa dicek unit test: routing, validasi Pydantic di level HTTP, status code, dependency injection.

Kedua level ini dibutuhkan berbarengan -- riwayat proyek ini sempat punya bug (`conversation_id=uuid.UUID` yang salah tanda baca) yang lolos dari unit test karena unit test tidak pernah lewat FastAPI routing sama sekali.

## 9. Keterbatasan yang Diketahui (Bukan Bug)

- **Single-user**: tidak ada autentikasi. Semua endpoint memakai `get_or_create_default_user()` -- satu user default untuk seluruh sistem. Ini keputusan sadar untuk MVP personal, bukan kelalaian. Kalau Thinker perlu multi-user, ini titik yang perlu didesain ulang (auth, `get_current_user` dependency, isolasi data per user).
- **Belum ada observability** (Bagian 17 di prompt awal): belum ada metrik latensi/token/biaya yang diekspos.
- **Belum ada cost control / model routing** (Bagian 18): satu model dipakai untuk semua tugas, belum ada logika "tugas sederhana -> model murah, tugas kompleks -> model kuat".
- **Belum ada frontend**: Vue 3 + TypeScript + Tailwind yang direncanakan di awal proyek belum diimplementasikan sama sekali.

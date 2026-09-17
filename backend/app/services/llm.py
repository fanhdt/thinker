"""Logika bisnis LLM Thinker -- Bagian 18 master prompt: Model-Agnostic
Architecture.

File ini SENGAJA tidak boleh import `google.genai` atau `openai` sama
sekali. Semua yang provider-spesifik (bentuk request, cara error dipetakan,
cara tool-calling dijalankan) hidup di `app/services/llm_providers/`.
`LLMService` di sini cuma menyusun prompt, memilih schema Pydantic, dan
memanggil `self._simple_provider.generate(...)` atau
`self._planner_provider.generate(...)` -- provider mana yang sebenarnya
dipakai per tier (Gemini, OpenAI, Groq, DeepSeek, atau rantai failover
di antaranya) ditentukan oleh `llm_providers.factory` berdasarkan config,
bukan oleh kode di sini. Tier "simple" (chat, routing, ekstraksi memori)
vs "planner" (pembuatan & eksekusi task) boleh diarahkan ke provider
berbeda -- lihat `build_simple_provider`/`build_planner_provider`.
"""

import logging
from typing import Literal

from pydantic import BaseModel

from app.core.logging_config import log_event
from app.services.llm_providers.base import LLMProvider, ProviderError
from app.services.llm_providers.factory import build_planner_provider, build_simple_provider

logger = logging.getLogger(__name__)


class MemoryExtraction(BaseModel):
    """Hasil analisis satu pesan user terhadap memory yang sudah tersimpan.

    `operation` menentukan apa yang harus dilakukan `memory_service`:
    - CREATE: `fact` (+ `importance`) baru, tidak berkaitan dengan memory lama.
    - UPDATE: `fact` (+ `importance`) baru menggantikan memory di `target_index`
      (mis. preferensi yang berubah).
    - DELETE: hapus memory di `target_index` (user minta dilupakan), `fact`
      tidak dipakai.
    - IGNORE: tidak ada fakta personal yang layak diingat/diubah.

    `target_index` WAJIB diisi untuk UPDATE/DELETE (index ke daftar
    existing memories yang dikirim ke prompt), dan diabaikan untuk
    CREATE/IGNORE.
    """

    operation: Literal["CREATE", "UPDATE", "DELETE", "IGNORE"]
    fact: str | None = None
    importance: int = 3
    target_index: int | None = None


class PlanTask(BaseModel):
    """Satu langkah kerja dalam sebuah Plan."""

    description: str


class Plan(BaseModel):
    """Bentuk Output TERSTRUKTUR planner (Fase 6)"""

    goal: str
    tasks: list[PlanTask]


class TaskOutcome(BaseModel):
    """Hasil `execute_and_evaluate`: mengerjakan task DAN mengevaluasi
    hasilnya sendiri dalam SATU panggilan LLM -- dulu ini 2 panggilan
    terpisah (`execute_task` + `evaluate_result`). Menghemat separuh
    panggilan LLM di reflection loop.
    """

    result: str
    is_correct: bool
    feedback: str = ""


class MessagePlan(BaseModel):
    """Hasil `classify_and_plan`: menentukan needs_planning DAN (kalau true)
    langsung membuat task-tasknya, dalam SATU panggilan -- dulu ini 2
    panggilan terpisah (`classify_message` + `create_plan`).

    `tasks` dikosongkan kalau `needs_planning=False`.
    """

    needs_planning: bool
    tasks: list[PlanTask] = []


class LLMServiceError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMService:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        simple_provider: LLMProvider | None = None,
        planner_provider: LLMProvider | None = None,
    ) -> None:
        """`provider`: suntik SATU provider dipakai untuk semua tier (dipakai
        test lama & kasus tanpa tiering). `simple_provider`/`planner_provider`:
        suntik provider berbeda per tier secara eksplisit (dipakai test
        tiering). Kalau semuanya None, masing-masing tier dibangun dari
        config lewat factory -- lihat `build_simple_provider`/
        `build_planner_provider` untuk aturan fallback-nya.
        """
        if provider is not None:
            self._simple_provider = provider
            self._planner_provider = provider
        else:
            self._simple_provider = (
                simple_provider if simple_provider is not None else build_simple_provider()
            )
            self._planner_provider = (
                planner_provider if planner_provider is not None else build_planner_provider()
            )

    @property
    def model(self) -> str:
        return self._simple_provider.model

    @property
    def planner_model(self) -> str:
        return self._planner_provider.model

    async def chat(self, message: str) -> str:
        try:
            outcome = await self._simple_provider.generate(
                [{"role": "user", "content": message}]
            )
        except ProviderError as exc:
            logger.error("Provider error: %s", exc)
            raise LLMServiceError(f"Gagal menghubungi LLM:{exc}", retryable=exc.retryable) from exc

        if not outcome.text:
            raise LLMServiceError("LLM mengembalikan response kosong")

        return outcome.text

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str:
        try:
            outcome = await self._simple_provider.generate(
                history, system_instruction=system_instruction, use_tools=True
            )
        except ProviderError as exc:
            logger.error("Provider error: %s", exc)
            raise LLMServiceError(f"Gagal menghubungi LLM: {exc}", retryable=exc.retryable) from exc

        if not outcome.text:
            raise LLMServiceError("LLM mengembalikan response kosong")

        return outcome.text

    async def extract_fact(
        self, message: str, existing_memories: list[str]
    ) -> MemoryExtraction | None:
        if existing_memories:
            memories_block = "\n".join(
                f"[{i}] {content}" for i, content in enumerate(existing_memories)
            )
        else:
            memories_block = "(belum ada memory tersimpan)"

        prompt = (
            "Analisis pesan berikut dari user sebuah asisten AI personal, "
            "dibandingkan dengan memory jangka panjang yang SUDAH tersimpan "
            "tentang user ini.\n\n"
            f"Memory yang sudah tersimpan (dengan index):\n{memories_block}\n\n"
            f'Pesan baru dari user: "{message}"\n\n'
            "Tentukan SATU `operation` yang paling tepat:\n"
            "- CREATE: pesan mengandung fakta personal baru (preferensi, "
            "kondisi kesehatan, pekerjaan, hubungan, kebiasaan, dsb) yang "
            "TIDAK bertentangan/berkaitan dengan memory manapun di atas.\n"
            "- UPDATE: pesan mengubah/menggantikan salah satu memory di atas "
            "(mis. preferensi yang berubah). Sebutkan `target_index`-nya.\n"
            "- DELETE: user secara eksplisit minta suatu fakta dilupakan/"
            "dihapus. Sebutkan `target_index`-nya.\n"
            "- IGNORE: pertanyaan biasa, basa-basi, atau tidak ada fakta "
            "personal yang layak diingat/diubah.\n\n"
            "Untuk CREATE/UPDATE, isi juga `fact`: tulis ulang sebagai satu "
            'kalimat singkat & netral berperspektif orang ketiga (mis. "User '
            'alergi kacang."), bukan mengutip mentah. Beri juga `importance` '
            "(1-5): 5 = sangat penting/menyangkut keselamatan & kesehatan "
            "(mis. alergi, kondisi medis), 3 = preferensi biasa (mis. "
            "makanan favorit), 1 = detail remeh.\n"
            "Untuk DELETE/IGNORE, `fact` tidak perlu diisi."
        )

        try:
            outcome = await self._simple_provider.generate(
                [{"role": "user", "content": prompt}], response_schema=MemoryExtraction
            )
        except ProviderError as exc:
            logger.error("Provider extraction error :%s", exc)
            raise LLMServiceError(f"Gagal ekstraksi memori :{exc}") from exc

        result = outcome.parsed if isinstance(outcome.parsed, MemoryExtraction) else None
        if result is None:
            logger.warning("LLM mengembalikan format ekstraksi memori yang tidak terduga")
            return None

        if result.operation in ("UPDATE", "DELETE"):
            valid_index = result.target_index is not None and 0 <= result.target_index < len(
                existing_memories
            )
            if not valid_index:
                logger.warning(
                    "LLM minta %s dengan target_index tidak valid (%s dari %d memory) "
                    "-- diperlakukan sebagai IGNORE",
                    result.operation,
                    result.target_index,
                    len(existing_memories),
                )
                return None

        if result.operation == "CREATE" and not result.fact:
            return None

        if result.operation == "IGNORE":
            return None

        return result

    async def create_plan(self, goal: str) -> Plan:
        """Dipakai oleh endpoint `/conversations/{id}/plan` yang MEMANG selalu
        ingin membuat plan langsung (user sudah eksplisit minta rencana, tidak
        perlu diklasifikasi dulu) -- beda dari jalur chat biasa yang lewat
        `classify_and_plan` (perlu tahu dulu apakah pesan butuh planning).
        """
        prompt = (
            "Anda adalah planner untuk asisten AI. Pecah goal berikut"
            "menjadi beberapa task KONKRET dan BERURUTAN yang -- kalau"
            "dikerjakan satu per satu -- akan mencapai goal tersebut.\n\n"
            f'Goal: "{goal}"\n\n'
            "Aturan:\n"
            "- Setiap task harus SPESIFIK dan bisa dikerjakan sendiri "
            "(bukan sub-goal abstrak).\n"
            "- Jangan buat lebih dari 6 task -- kalau goal-nya sangat "
            "sederhana, 1-2 task saja cukup.\n"
            "- Urutkan task sesuai urutan pengerjaan yang logis."
        )

        try:
            outcome = await self._planner_provider.generate(
                [{"role": "user", "content": prompt}], response_schema=Plan
            )
        except ProviderError as exc:
            logger.error("Provider planning error:%s", exc)
            raise LLMServiceError(f"Gagal membuat plan:{exc}") from exc

        plan = outcome.parsed if isinstance(outcome.parsed, Plan) else None
        if plan is None:
            raise LLMServiceError("LLM mengembalikan plan yang tidak valid.")
        return plan

    async def classify_and_plan(self, message: str) -> MessagePlan:
        """Gabungan `classify_message` + `create_plan` dalam SATU panggilan.

        Dulu: 1 panggilan untuk tanya "perlu planning?", lalu KALAU ya, 1
        panggilan lagi untuk minta plan-nya. Sekarang keduanya diminta
        sekaligus -- model tetap boleh menjawab needs_planning=False dengan
        `tasks` kosong, tidak ada perilaku yang hilang, cuma jadi 1 request.

        Sengaja pakai `_simple_provider` (bukan `_planner_provider`) walau
        method ini juga menyusun task -- dipanggil di SETIAP pesan user
        (keputusan routing), jadi harus tetap murah/cepat. Kualitas
        pemecahan task tidak terlalu kritis di sini karena pekerjaan berat
        yang sesungguhnya ada di `execute_and_evaluate` (tier planner).
        """
        prompt = (
            "Tentukan apakah pesan berikut BUTUH RENCANA BERTAHAP"
            "(dipecah jadi beberapa langkah berurutan) untuk "
            "diselesaikan dengan baik, atau cukup dijawab LANGSUNG"
            "dalam satu balasan chat biasa.\n\n"
            f'Pesan: "{message}"\n\n'
            "needs_planning=true HANYA kalo pesan ini benar-benar"
            "meminta sesuatu yang KOMPLEKS dan berlangkah langkah"
            '(mis. "rencanakan...", "buatkan rencana...", "bantu aku '
            'mempersiapkan..." untuk hal yang butuh beberapa tahap '
            "berurutan). Pertanyaan biasa, obrolan, permintaan info "
            "sederhana, atau perhitungan langsung -> needs_planning=false.\n\n"
            "KALAU needs_planning=true, isi juga `tasks`: pecah pesan itu "
            "menjadi beberapa task KONKRET dan BERURUTAN yang -- kalau "
            "dikerjakan satu per satu -- akan memenuhi permintaan itu. "
            "Setiap task harus SPESIFIK dan bisa dikerjakan sendiri (bukan "
            "sub-goal abstrak). Jangan buat lebih dari 6 task -- kalau "
            "permintaannya sangat sederhana, 1-2 task saja cukup. Urutkan "
            "task sesuai urutan pengerjaan yang logis.\n"
            "KALAU needs_planning=false, `tasks` dikosongkan saja ([])."
        )

        try:
            outcome = await self._simple_provider.generate(
                [{"role": "user", "content": prompt}], response_schema=MessagePlan
            )
        except ProviderError as exc:
            logger.error("Provider routing/planning error: %s", exc)
            return MessagePlan(needs_planning=False, tasks=[])

        result = outcome.parsed if isinstance(outcome.parsed, MessagePlan) else None
        if result is None:
            logger.warning("LLM mengembalikan format classify_and_plan yang tak terduga")
            log_event(
                logger, "llm_parse_failed", method="classify_and_plan", raw_response=outcome.text
            )
            return MessagePlan(needs_planning=False, tasks=[])
        return result

    async def execute_and_evaluate(self, task_description: str, prior_context: str) -> TaskOutcome:
        """Gabungan `execute_task` + `evaluate_result` dalam SATU panggilan.

        Dulu: 1 panggilan untuk mengerjakan task, lalu 1 panggilan terpisah
        untuk minta model lain (sebenarnya model yang sama, request beda)
        menilai hasilnya. Sekarang model diminta mengerjakan task DAN
        menilai hasilnya sendiri dalam satu respons terstruktur.

        `use_tools=True` -- provider boleh memakai tools (kalkulator,
        datetime, web search) untuk mengerjakan task, sama seperti sebelumnya.
        """
        prompt = f'Kerjakan task berikut: "{task_description}"'
        if prior_context:
            prompt += (
                f"\n\nKonteks dari task-task sebelumnya yang sudah dikerjakan:\n {prior_context}"
            )
        prompt += (
            "\n\nSetelah mengerjakan, evaluasi SENDIRI hasil kamu: isi "
            "`is_correct=true` kalau hasil sudah cukup baik dan relevan "
            "dengan task. Kalau ada yang kurang, salah, atau tidak relevan, "
            "isi `is_correct=false` dan isi `feedback` dengan penjelasan "
            "SINGKAT apa yang perlu diperbaiki."
        )

        try:
            outcome = await self._planner_provider.generate(
                [{"role": "user", "content": prompt}],
                response_schema=TaskOutcome,
                use_tools=True,
            )
        except ProviderError as exc:
            logger.error("Provider task execution error : %s", exc)
            raise LLMServiceError(
                f"Gagal menjalankan task '{task_description}':{exc}", retryable=exc.retryable
            ) from exc

        result = outcome.parsed if isinstance(outcome.parsed, TaskOutcome) else None
        if result is None:
            logger.warning(
                "LLM mengembalikan format execute_and_evaluate yang tak terduga, "
                "fallback ke is_correct=True"
            )
            log_event(
                logger, "llm_parse_failed", method="execute_and_evaluate", raw_response=outcome.text
            )
            result = TaskOutcome(result=outcome.text or "", is_correct=True, feedback="")

        if not result.result:
            raise LLMServiceError(
                f"LLM mengembalikan hasil kosong untuk task '{task_description}'."
            )
        return result


llm_service = LLMService()
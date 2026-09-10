import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging_config import log_event
from app.services.tools.registry import AVAILABLE_TOOLS

MAX_TOOL_CALLS_PER_REQUEST = 5

logger = logging.getLogger(__name__)


def _extract_usage(response) -> dict[str, int]:
    """Ambil token usage dari response Gemini secara defensif.

    `usage_metadata` bisa saja tidak ada (mis. versi SDK berbeda, atau
    response mock di test) -- observability tidak boleh sampai menjadi
    penyebab request asli meledak, jadi field yang tidak ada cukup
    di-skip, bukan raise.
    """

    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    fields = {
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
    }
    return {k: v for k, v in fields.items() if v is not None}


def _as_structured[T: BaseModel](response, model_cls: type[T]) -> T | None:
    """Validasi tipe `response.parsed` dari gemini secara eksplisit .
    SDK mengetik `respon.parsed` secara generik (`BaseModel | Dict | Enum | None`)
    karena dia tidak tau skema spesifik yang kita minta
    lewat `response_schema` .
    Mengklaim tipenya lewat anotasi variabel saja
    (mis. `plan:Plan | None = response.parsed`)
    TIDAK memvalidasi apapun secara runtime --
    kalau gemini pernah mengembalikan bentuk yang tak terduga
    kode akan lanjut jalan dengan asumsi tipe yang salah,
    lalu meledak entah dimana di hilir.
    Fungsi ini memastikan validasi itu benar benar terjadi di satu tempat.
    """
    parsed = response.parsed
    return parsed if isinstance(parsed, model_cls) else None


class MemoryExtraction(BaseModel):
    has_memory: bool
    fact: str | None = None
    importance: int = 3


class PlanTask(BaseModel):
    """Satu langkah kerja dalam sebuah Plan."""

    description: str


class Plan(BaseModel):
    """Bentuk Output TERSTRUKTUR planner (Fase 6)"""

    goal: str
    tasks: list[PlanTask]


class TaskEvaluation(BaseModel):
    is_correct: bool
    feedback: str = ""


class MessageRoute(BaseModel):
    needs_planning: bool


class LLMServiceError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMService:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    @property
    def model(self) -> str:
        return self._model

    async def _generate(
        self,
        *,
        method: str,
        contents,
        config: types.GenerateContentConfig | None = None,
    ):
        """Bungkus `generate_content` dengan timing + structured logging.

        Satu tempat ini dipakai oleh ketujuh method publik di bawah supaya
        tiap panggilan ke Gemini otomatis tercatat (durasi, sukses/gagal,
        token usage kalau tersedia) tanpa menduplikasi try/except di
        masing-masing method. `APIError` sengaja dilempar ulang apa adanya
        (bukan dibungkus di sini) -- tiap method publik yang menentukan
        pesan error & retryable-nya sendiri, sesuai perilaku yang sudah ada.
        """
        method_start = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except APIError as exc:
            duration_ms = round((time.perf_counter() - method_start) * 1000, 1)
            log_event(
                logger,
                "llm_call",
                method=method,
                duration_ms=duration_ms,
                success=False,
                error=str(exc),
            )
            raise

        duration_ms = round((time.perf_counter() - method_start) * 1000, 1)
        log_event(
            logger,
            "llm_call",
            method=method,
            duration_ms=duration_ms,
            success=True,
            **_extract_usage(response),
        )
        return response

    async def chat(self, message: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=message,
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429, 503)
            raise LLMServiceError(f"Gagal menghubungi gemini:{exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text

    async def chat_with_history(
        self, history: list[dict[str, str]], *, system_instruction: str | None = None
    ) -> str:
        contents = [
            {
                "role": "user" if turn["role"] == "user" else "model",
                "parts": [{"text": turn["content"]}],
            }
            for turn in history
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=AVAILABLE_TOOLS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_TOOL_CALLS_PER_REQUEST
            ),
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except APIError as exc:
            logger.error("Gemini API error: %s", exc)
            retryable = exc.code in (429, 503)
            raise LLMServiceError(f"Gagal menghubungi Gemini: {exc}", retryable=retryable) from exc

        if not response.text:
            raise LLMServiceError("Gemini mengembalikan response kosong")

        return response.text

    async def extract_fact(self, message: str) -> MemoryExtraction | None:
        prompt = (
            "Analisis pesan berikut dari user sebuah asisten AI personal.\n"
            "Apakah pesan ini mengandung FAKTA PERSONAL yang layak diingat "
            "jangka panjang (preferensi, kondisi kesehatan, pekerjaan, "
            "hubungan, kebiasaan, dsb)? Pertanyaan biasa atau basa-basi "
            "BUKAN fakta yang perlu diingat.\n\n"
            f'Pesan: "{message}"\n\n'
            "Kalau ADA fakta, tulis ulang sebagai satu kalimat singkat & "
            'netral berperspektif orang ketiga (mis. "User alergi kacang."), '
            "bukan mengutip mentah. Beri juga `importance` (1 - 5):"
            "5 = Sangat penting/menyangkut keselamatan dan kesehatan"
            "(mis. alergi, kondisi medis), 3 = preferensi biasa"
            "(mis. makanan favorit), 1 = detail remeh"
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MemoryExtraction,
                ),
            )
        except APIError as exc:
            logger.error("Gemini extraction error :%s", exc)
            raise LLMServiceError(f"Gagal ekstraksi memori :{exc}") from exc

        result = _as_structured(response, MemoryExtraction)
        if result is None:
            logger.warning("Gemini mengembalikan format ekstraksi memori yang tidak terduga")
            return None
        if result.has_memory and result.fact:
            return result
        return None

    async def create_plan(self, goal: str) -> Plan:
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
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Plan,
                ),
            )
        except APIError as exc:
            logger.error("Gemini planning erreor:%s", exc)
            raise LLMServiceError(f"Gagal membuat plan:{exc}") from exc

        plan = _as_structured(response, Plan)
        if plan is None:
            raise LLMServiceError("Gemini mengembalikan plan yang tidak valid.")
        return plan

    async def execute_task(self, task_description: str, prior_context: str) -> str:
        prompt = f'Kerjakan task berikut: "{task_description}"'
        if prior_context:
            prompt += (
                f"\n\nKonteks dari task-task sebelumnya yang sudahdikerjakan:\n {prior_context}"
            )

        config = types.GenerateContentConfig(
            tools=AVAILABLE_TOOLS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_TOOL_CALLS_PER_REQUEST
            ),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=config,
            )
        except APIError as exc:
            logger.error("Gemini task execution error : %s", exc)
            retryable = exc.code in (429, 503)
            raise LLMServiceError(
                f"Gagal menjalankan task '{task_description}':{exc}", retryable=retryable
            ) from exc

        if not response.text:
            raise LLMServiceError(
                f"Gemin mengembalikan hasil kosong untuk task '{task_description}'."
            )
        return response.text

    async def evaluate_result(self, task_description: str, result: str) -> TaskEvaluation:
        prompt = (
            "Evaluasi apakah Hasil berikut benar benar menyelesaikan "
            "Task dengan baik. \n\n"
            f'Task: "{task_description}"\n\n'
            f"Hasil:\n{result}\n\n"
            "Kalau hasil sudah cukup baik dan relevan, jawab is_correct=true."
            "Kalau ada yang kurang, salah, atau tidak relevan dengan task, "
            "jawab is_correct=false dan isi 'feedback' dengan penjealsan"
            "SINGKAT apa yang perlu diperbaiki"
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TaskEvaluation,
                ),
            )
        except APIError as exc:
            logger.error("Gemini evaluation error: %s", exc)
            raise LLMServiceError(f"Gagal mengevaluasi hasil : {exc}") from exc

        evaluation = _as_structured(response, TaskEvaluation)

        if evaluation is None:
            logger.warning(
                "Gemini mengembalikan format evaluasi yang tak terduga, fallback ke is_correct=True"
            )
            return TaskEvaluation(is_correct=True, feedback="")

        return evaluation

    async def classify_message(self, message: str) -> bool:
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
            "sederhana, atau perhitungan langsung -> needs_planning=false."
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MessageRoute,
                ),
            )
        except APIError as exc:
            logger.error("Gemini routing error: %s", exc)
            return False

        route = _as_structured(response, MessageRoute)
        return route.needs_planning if route else False


llm_service = LLMService()

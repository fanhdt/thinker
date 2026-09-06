import httpx

SEARCH_TIMEOUT_SECONDS = 10
MAX_RELATED_TOPICS = 3


def web_search(query: str) -> str:
    """Cari informasi singkat di web untuk topik tertentu.

    Gunakan tool ini kalau butuh informasi  tekini
    yang mungkin tidak kamu ketahui (kejadian terbaru, data yang sering berubah, dsb).
    Hasil yang dikembalikan berupa ringkasan singkat, bukan artikel lengkap

    Args:
        query : Kata kunci pencarian
    """

    try:
        with httpx.Client(timeout=SEARCH_TIMEOUT_SECONDS) as client:
            response = client.get(
                "https://api.duckduckgo.com",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        return f"Gagal melakukan pencarian :{exc}"

    abstract = data.get("AbstractText") or ""
    related_topics = data.get("RelatedTopics", [])[:MAX_RELATED_TOPICS]
    related = [t["Text"] for t in related_topics if isinstance(t, dict) and t.get("Text")]

    parts = []

    if abstract:
        parts.append(abstract)
    if related:
        related_lines = "\n".join(f"- {r}" for r in related)
        parts.append(f"info terkait:\n{related_lines}")

    return "\n\n".join(parts)

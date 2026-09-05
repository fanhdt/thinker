from app.services.document_service import chunk_text


def test_chunk_text_empty_string_return_empty_list():
    assert chunk_text("") == []
    assert chunk_text(" ") == []


def test_chunk_text_shorter_than_chunk_size_returns_one_chunk():
    text = "Ini teks pendek"
    chunks = chunk_text(text, chunk_size=1000, overlap=200)
    assert chunks == [text]


def test_chunk_text_splits_long_text_into_multiple_chunks():
    text = "A" * 250
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1


def test_chunk_text_respects_overlap():
    text = "".join(str(i % 10) for i in range(250))
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    overlap_expected = text[80:100]
    assert chunks[1].startswith(overlap_expected)


def test_chunk_text_no_data_loss_at_boundaries():
    text = "".join(str(i % 10) for i in range(500))
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    combined = "".join(chunks)
    for char in text:
        assert char in combined

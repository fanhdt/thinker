from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dev_frontend_origin_gets_cors_header():
    """Frontend (Vite, http://localhost:5173) harus bisa panggil backend ini.

    Regression test untuk fix CORSMiddleware -- kalau suatu saat middleware
    ini kehapus/berubah tanpa sengaja saat refactor main.py, test ini gagal
    duluan sebelum baru ketahuan manual lewat browser (dan bingung kenapa
    fetch() gagal tanpa pesan error yang jelas di console).
    """
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unlisted_origin_does_not_get_cors_header():
    """Origin yang tidak didaftarkan tidak boleh diizinkan diam-diam.

    Ini menjaga agar fix di atas tetap allowlist eksplisit, bukan tergelincir
    jadi wildcard "*" di masa depan tanpa ada yang sadar.
    """
    response = client.get(
        "/health",
        headers={"Origin": "http://evil.example.com"},
    )

    assert "access-control-allow-origin" not in response.headers
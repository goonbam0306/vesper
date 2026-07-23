from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_frontend_does_not_embed_sqlite_or_secret_material():
    frontend = REPO / "frontend"
    source_files = [frontend / "index.html", *sorted((frontend / "src").glob("*"))]
    source = "\n".join(p.read_text(encoding="utf-8") for p in source_files if p.is_file() and p.suffix in {".ts", ".tsx", ".js", ".jsx", ".html"})
    assert "sqlite3" not in source.lower()
    assert "password" not in source.lower()
    assert "secret_value" not in source.lower()


def test_frontend_only_uses_api_surface():
    assert (REPO / "frontend" / "src" / "main.tsx").exists()
    assert not (REPO / "frontend" / "src" / "database.ts").exists()

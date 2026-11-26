import pytest

from app.verification.evidence import EvidenceEngine


@pytest.mark.asyncio
async def test_generate_rejects_paths_outside_repository(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("must not be exposed", encoding="utf-8")

    evidence = await EvidenceEngine().generate(
        {"file_path": "../secret.txt", "line_number": 1},
        str(repo_path),
    )

    assert evidence is None


@pytest.mark.asyncio
async def test_generate_rejects_symlinks_outside_repository(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("must not be exposed", encoding="utf-8")
    (repo_path / "linked.txt").symlink_to(outside_file)

    evidence = await EvidenceEngine().generate(
        {"file_path": "linked.txt", "line_number": 1},
        str(repo_path),
    )

    assert evidence is None


@pytest.mark.asyncio
async def test_generate_still_returns_snippets_for_repository_files(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    source_file = repo_path / "module.py"
    source_file.write_text("first line\nsecond line\nthird line\n", encoding="utf-8")

    evidence = await EvidenceEngine().generate(
        {"file_path": "module.py", "line_number": 2},
        str(repo_path),
    )

    assert evidence is not None
    assert evidence["evidence_type"] == "SNIPPET"
    assert "module.py:2" in evidence["content"]
    assert "second line" in evidence["content"]

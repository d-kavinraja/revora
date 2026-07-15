"""Tests for RepoWalker module."""

import pytest
import asyncio
import os
import tempfile
from app.intelligence.repo_walker import RepoWalker


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository structure for testing."""
    # Create Python files
    (tmp_path / "main.py").write_text("import os\nprint('hello')")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    (tmp_path / "models.py").write_text("class User: pass")

    # Create JS files
    (tmp_path / "index.js").write_text("console.log('hello')")
    (tmp_path / "app.ts").write_text("const x: number = 1")

    # Create subdirectory
    subdir = tmp_path / "src"
    subdir.mkdir()
    (subdir / "module.py").write_text("import sys")

    # Create config files
    (tmp_path / "package.json").write_text('{"name": "test"}')
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]")

    # Create test file
    (tmp_path / "test_main.py").write_text("def test_hello(): assert True")

    # Create file that should be skipped
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"\x00")

    return tmp_path


@pytest.mark.asyncio
async def test_repo_walker_basic(temp_repo):
    """Test basic RepoWalker functionality."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    assert walker.file_count > 0
    assert len(walker.extensions) > 0
    assert walker._walked is True


@pytest.mark.asyncio
async def test_repo_walker_file_paths(temp_repo):
    """Test file path collection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    # Should not include .pyc files
    assert not any(fp.endswith(".pyc") for fp in walker.file_paths)

    # Should include Python files
    py_files = walker.get_files_by_extension(".py")
    assert len(py_files) >= 3  # main.py, utils.py, models.py, test_main.py, src/module.py


@pytest.mark.asyncio
async def test_repo_walker_extensions(temp_repo):
    """Test extension counting."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    extensions = walker.extensions
    assert ".py" in extensions
    assert ".js" in extensions or ".ts" in extensions


@pytest.mark.asyncio
async def test_repo_walker_get_content(temp_repo):
    """Test file content retrieval."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    content = await walker.get_content("main.py")
    assert "import os" in content
    assert "print('hello')" in content


@pytest.mark.asyncio
async def test_repo_walker_get_content_missing(temp_repo):
    """Test handling of missing files."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    content = await walker.get_content("nonexistent.py")
    assert content == ""


@pytest.mark.asyncio
async def test_repo_walker_get_files_by_extension(temp_repo):
    """Test filtering by extension."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    py_files = walker.get_files_by_extension(".py")
    assert all(fp.endswith(".py") for fp in py_files)

    js_files = walker.get_files_by_extension(".js")
    assert all(fp.endswith(".js") for fp in js_files)


@pytest.mark.asyncio
async def test_repo_walker_get_files_by_pattern(temp_repo):
    """Test pattern matching."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    test_files = walker.get_files_by_pattern("test_*.py")
    assert len(test_files) >= 1
    assert all("test_" in fp for fp in test_files)


@pytest.mark.asyncio
async def test_repo_walker_language_distribution(temp_repo):
    """Test language distribution."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    dist = walker.get_language_distribution()
    assert "Python" in dist
    assert dist["Python"] >= 3


@pytest.mark.asyncio
async def test_repo_walker_skip_dirs(temp_repo):
    """Test that skip directories are excluded."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    # __pycache__ files should be skipped
    assert not any("__pycache__" in fp for fp in walker.file_paths)


@pytest.mark.asyncio
async def test_repo_walker_empty_repo(tmp_path):
    """Test handling of empty repository."""
    walker = RepoWalker(str(tmp_path))
    await walker.walk()

    assert walker.file_count == 0
    assert walker.extensions == {}


@pytest.mark.asyncio
async def test_repo_walker_nonexistent_repo():
    """Test handling of nonexistent repository path."""
    walker = RepoWalker("/nonexistent/path/to/repo")
    await walker.walk()

    assert walker.file_count == 0
    assert walker.extensions == {}


@pytest.mark.asyncio
async def test_repo_walker_content_caching(temp_repo):
    """Test that file content is cached."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    # First read
    content1 = await walker.get_content("main.py")
    # Second read (should be cached)
    content2 = await walker.get_content("main.py")

    assert content1 == content2


@pytest.mark.asyncio
async def test_repo_walker_max_chars(temp_repo):
    """Test file content size limit."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    content = await walker.get_content("main.py", max_chars=5)
    assert len(content) <= 5

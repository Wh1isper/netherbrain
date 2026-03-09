"""Unit tests for the file operations manager.

Pure filesystem tests -- no DB, no Docker, no integration markers.
Uses pytest's ``tmp_path`` fixture for isolated test directories.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netherbrain.agent_runtime.managers.files import (
    FileListResult,
    ProjectPathResolver,
    build_archive,
    list_directory,
    read_file,
    resolve_download,
    save_upload,
    write_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    """Create a data root with a project directory."""
    projects = tmp_path / "projects"
    projects.mkdir()
    return tmp_path


@pytest.fixture()
def project_dir(data_root: Path) -> Path:
    """Create a sample project with some files."""
    proj = data_root / "projects" / "test-project"
    proj.mkdir()

    # Create a directory structure:
    # test-project/
    #   README.md
    #   src/
    #     main.py
    #     utils/
    #       helpers.py
    #   data/
    #     config.yaml
    (proj / "README.md").write_text("# Test Project\n")
    (proj / "src").mkdir()
    (proj / "src" / "main.py").write_text("import sys\nprint('hello')\n")
    (proj / "src" / "utils").mkdir()
    (proj / "src" / "utils" / "helpers.py").write_text("def helper(): pass\n")
    (proj / "data").mkdir()
    (proj / "data" / "config.yaml").write_text("key: value\n")
    return proj


@pytest.fixture()
def resolver(data_root: Path) -> ProjectPathResolver:
    """Create a resolver pointed at the test data root."""
    return ProjectPathResolver(data_root=str(data_root))


# ---------------------------------------------------------------------------
# Path resolver tests
# ---------------------------------------------------------------------------


class TestProjectPathResolver:
    def test_resolve_project_root(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        root = resolver.resolve("test-project")
        assert root == project_dir.resolve()

    def test_resolve_subpath(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        target = resolver.resolve("test-project", "src/main.py")
        assert target == (project_dir / "src" / "main.py").resolve()

    def test_resolve_empty_path(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        root = resolver.resolve("test-project", "")
        assert root == project_dir.resolve()

    def test_resolve_dot_path(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        root = resolver.resolve("test-project", ".")
        assert root == project_dir.resolve()

    def test_project_not_found(self, resolver: ProjectPathResolver) -> None:
        with pytest.raises(LookupError, match="not found"):
            resolver.resolve("nonexistent")

    def test_path_traversal_blocked(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(PermissionError, match="escapes"):
            resolver.resolve("test-project", "../../etc/passwd")

    def test_path_traversal_with_dotdot(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(PermissionError, match="escapes"):
            resolver.resolve("test-project", "src/../../..")

    def test_symlink_escape_blocked(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Create a symlink pointing outside the project
        link = project_dir / "escape"
        link.symlink_to("/tmp")  # noqa: S108
        with pytest.raises(PermissionError, match="escapes"):
            resolver.resolve("test-project", "escape")

    def test_symlink_within_project_allowed(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Create a symlink within the project
        link = project_dir / "link_to_src"
        link.symlink_to(project_dir / "src")
        target = resolver.resolve("test-project", "link_to_src")
        assert target == (project_dir / "src").resolve()

    def test_with_prefix(self, tmp_path: Path) -> None:
        # Test with data_prefix
        (tmp_path / "myprefix" / "projects" / "proj").mkdir(parents=True)
        r = ProjectPathResolver(data_root=str(tmp_path), data_prefix="myprefix")
        root = r.resolve("proj")
        assert root == (tmp_path / "myprefix" / "projects" / "proj").resolve()


# ---------------------------------------------------------------------------
# list_directory tests
# ---------------------------------------------------------------------------


class TestListDirectory:
    def test_list_root(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project")
        assert isinstance(result, FileListResult)
        assert result.project_id == "test-project"
        assert result.path == ""

        names = [e.name for e in result.entries]
        # Directories first (alphabetical), then files
        assert names == ["data", "src", "README.md"]

    def test_list_subdirectory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project", "src")
        names = [e.name for e in result.entries]
        assert names == ["utils", "main.py"]

    def test_list_nested(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project", "src/utils")
        assert len(result.entries) == 1
        assert result.entries[0].name == "helpers.py"
        assert result.entries[0].type == "file"
        assert result.entries[0].size is not None
        assert result.entries[0].size > 0

    def test_list_empty_directory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        (project_dir / "empty").mkdir()
        result = list_directory(resolver, "test-project", "empty")
        assert result.entries == []

    def test_list_nonexistent_directory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError):
            list_directory(resolver, "test-project", "nonexistent")

    def test_list_file_not_directory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError, match="Not a directory"):
            list_directory(resolver, "test-project", "README.md")

    def test_entry_types(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project")
        types = {e.name: e.type for e in result.entries}
        assert types["data"] == "directory"
        assert types["src"] == "directory"
        assert types["README.md"] == "file"

    def test_entry_paths_are_relative(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project", "src")
        for entry in result.entries:
            assert entry.path.startswith("src/")
            assert not Path(entry.path).is_absolute()

    def test_dirs_have_no_size(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = list_directory(resolver, "test-project")
        for entry in result.entries:
            if entry.type == "directory":
                assert entry.size is None


# ---------------------------------------------------------------------------
# read_file tests
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_read_text_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = read_file(resolver, "test-project", "README.md")
        assert result.content == "# Test Project\n"
        assert result.size > 0
        assert result.truncated is False
        assert result.encoding == "utf-8"

    def test_read_nested_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = read_file(resolver, "test-project", "src/main.py")
        assert "import sys" in result.content

    def test_binary_file_rejected(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        (project_dir / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
        with pytest.raises(ValueError, match="Binary file"):
            read_file(resolver, "test-project", "binary.bin")

    def test_large_file_truncated(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Write a file larger than max_size
        content = "x" * 200
        (project_dir / "big.txt").write_text(content)
        result = read_file(resolver, "test-project", "big.txt", max_size=100)
        assert result.truncated is True
        assert len(result.content) == 100

    def test_file_not_found(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError, match="not found"):
            read_file(resolver, "test-project", "nonexistent.txt")

    def test_directory_not_readable(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError, match="not found"):
            read_file(resolver, "test-project", "src")

    def test_latin1_fallback(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Write bytes that are valid latin-1 but not valid utf-8
        (project_dir / "latin.txt").write_bytes(b"caf\xe9\n")
        result = read_file(resolver, "test-project", "latin.txt")
        assert result.encoding == "latin-1"
        assert "caf" in result.content


# ---------------------------------------------------------------------------
# write_file tests
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_write_new_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = write_file(resolver, "test-project", "new.txt", "hello world")
        assert result.size > 0
        assert (project_dir / "new.txt").read_text() == "hello world"

    def test_write_creates_parent_dirs(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        result = write_file(resolver, "test-project", "deep/nested/file.txt", "content")
        assert result.path == "deep/nested/file.txt"
        assert (project_dir / "deep" / "nested" / "file.txt").read_text() == "content"

    def test_write_overwrites_existing(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        write_file(resolver, "test-project", "README.md", "updated content")
        assert (project_dir / "README.md").read_text() == "updated content"

    def test_write_atomic(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Write a file, then check no .tmp files remain
        write_file(resolver, "test-project", "atomic.txt", "data")
        tmp_files = list(project_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_write_path_traversal_blocked(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(PermissionError):
            write_file(resolver, "test-project", "../escape.txt", "bad")


# ---------------------------------------------------------------------------
# save_upload tests
# ---------------------------------------------------------------------------


class TestSaveUpload:
    def test_upload_to_root(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        info = save_upload(resolver, "test-project", "", "upload.txt", b"file data")
        assert info.path == "upload.txt"
        assert info.size == 9
        assert (project_dir / "upload.txt").read_bytes() == b"file data"

    def test_upload_to_subdirectory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        info = save_upload(resolver, "test-project", "data", "new.csv", b"a,b,c\n")
        assert info.path == "data/new.csv"
        assert (project_dir / "data" / "new.csv").exists()

    def test_upload_creates_directory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        info = save_upload(resolver, "test-project", "uploads/2025", "photo.jpg", b"\xff\xd8")
        assert info.path == "uploads/2025/photo.jpg"
        assert (project_dir / "uploads" / "2025" / "photo.jpg").exists()

    def test_upload_size_limit(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        data = b"x" * 1000
        with pytest.raises(ValueError, match="exceeds size limit"):
            save_upload(resolver, "test-project", "", "big.bin", data, max_file_size=500)


# ---------------------------------------------------------------------------
# resolve_download tests
# ---------------------------------------------------------------------------


class TestResolveDownload:
    def test_download_existing_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        real_path, mime = resolve_download(resolver, "test-project", "README.md")
        assert real_path == (project_dir / "README.md").resolve()
        assert "text" in mime or "markdown" in mime  # text/markdown or text/plain

    def test_download_python_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        real_path, _mime = resolve_download(resolver, "test-project", "src/main.py")
        assert real_path.exists()

    def test_download_nonexistent(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError, match="not found"):
            resolve_download(resolver, "test-project", "nope.txt")

    def test_download_directory_rejected(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError, match="not found"):
            resolve_download(resolver, "test-project", "src")


# ---------------------------------------------------------------------------
# build_archive tests
# ---------------------------------------------------------------------------


class TestBuildArchive:
    def test_archive_single_file(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        import zipfile

        buf = build_archive(resolver, "test-project", ["README.md"])
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert "README.md" in names
            assert zf.read("README.md") == b"# Test Project\n"

    def test_archive_directory(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        import zipfile

        buf = build_archive(resolver, "test-project", ["src"])
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert "src/main.py" in names
            assert "src/utils/helpers.py" in names

    def test_archive_mixed(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        import zipfile

        buf = build_archive(resolver, "test-project", ["README.md", "src"])
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert "README.md" in names
            assert "src/main.py" in names

    def test_archive_size_guard(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        # Create a file that exceeds the size limit
        (project_dir / "huge.txt").write_text("x" * 1000)
        with pytest.raises(ValueError, match="exceeds size limit"):
            build_archive(resolver, "test-project", ["huge.txt"], max_total_size=500)

    def test_archive_nonexistent_path(self, resolver: ProjectPathResolver, project_dir: Path) -> None:
        with pytest.raises(LookupError):
            build_archive(resolver, "test-project", ["nonexistent.txt"])

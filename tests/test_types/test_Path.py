import os
import pathlib
import platform
import subprocess
import sys
import tempfile

import pytest

import click


def test_path_dash_no_byteswarning():
    """Detecting the ``-`` dash sentinel must not compare ``bytes`` against
    ``str``, which raises a ``BytesWarning`` under ``python -bb``.

    The warning is only emitted when the interpreter runs with ``-b``, so this
    has to be checked in a subprocess. ``-bb`` turns the warning into an error,
    so a clean exit means no mismatched comparison happened.
    """
    program = (
        "import click\n"
        "convert = click.Path(allow_dash=True).convert\n"
        "for value in ('-', '', b'-', b''):\n"
        "    convert(value, None, None)\n"
    )
    result = subprocess.run(
        [sys.executable, "-bb", "-c", program],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "BytesWarning" not in result.stderr


def _symlinks_supported():
    with tempfile.TemporaryDirectory(prefix="click-pytest-") as tempdir:
        target = os.path.join(tempdir, "target")
        open(target, "w").close()
        link = os.path.join(tempdir, "link")

        try:
            os.symlink(target, link)
            return True
        except OSError:
            return False


@pytest.mark.skipif(
    not _symlinks_supported(), reason="The current OS or FS doesn't support symlinks."
)
def test_path_resolve_symlink(tmp_path, runner):
    test_file = tmp_path / "file"
    test_file_str = os.fspath(test_file)
    test_file.write_text("")

    path_type = click.Path(resolve_path=True)
    param = click.Argument(["a"], type=path_type)
    ctx = click.Context(click.Command("cli", params=[param]))

    test_dir = tmp_path / "dir"
    test_dir.mkdir()

    abs_link = test_dir / "abs"
    abs_link.symlink_to(test_file)
    abs_rv = path_type.convert(os.fspath(abs_link), param, ctx)
    assert abs_rv == test_file_str

    rel_link = test_dir / "rel"
    rel_link.symlink_to(pathlib.Path("..") / "file")
    rel_rv = path_type.convert(os.fspath(rel_link), param, ctx)
    assert rel_rv == test_file_str


def test_path_expand_user(tmp_path, monkeypatch):
    """``expand_user=True`` expands ``~`` in the value itself, so paths from
    env vars, config files, or quoted args resolve to the home directory."""
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setenv("USERPROFILE", os.fspath(tmp_path))
    test_file = tmp_path / "file"
    test_file.touch()

    type = click.Path(exists=True, expand_user=True)
    assert type.convert("~/file", None, None) == os.fspath(test_file)
    assert type.convert("~", None, None) == os.fspath(tmp_path)


def test_path_expand_user_envvar(tmp_path, monkeypatch, runner):
    """Values that arrive through an env var are expanded."""
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setenv("USERPROFILE", os.fspath(tmp_path))
    (tmp_path / "file").touch()

    @click.command()
    @click.option("-f", type=click.Path(exists=True, expand_user=True), envvar="F")
    def cli(f):
        return f

    result = runner.invoke(cli, env={"F": "~/file"}, standalone_mode=False)
    assert result.return_value == os.fspath(tmp_path / "file")


def test_path_expand_user_named(tmp_path, monkeypatch):
    """The ``~user`` form expands to that user's home. ``~user`` is not
    expanded on Windows, and ``getpwnam`` ignores ``HOME``, so the lookup is
    faked to point at ``tmp_path``."""
    pwd = pytest.importorskip("pwd")
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda name: pwd.struct_passwd((name, "", 0, 0, "", os.fspath(tmp_path), "")),
    )
    test_file = tmp_path / "file"
    test_file.touch()

    type = click.Path(exists=True, expand_user=True)
    assert type.convert("~someone/file", None, None) == os.fspath(test_file)


def test_path_expand_user_resolve(tmp_path, monkeypatch):
    """``expand_user`` composes with ``resolve_path``: expand first, then
    resolve."""
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setenv("USERPROFILE", os.fspath(tmp_path))
    test_file = tmp_path / "file"
    test_file.touch()

    type = click.Path(exists=True, expand_user=True, resolve_path=True)
    assert type.convert("~/file", None, None) == os.path.realpath(test_file)


def test_path_expand_user_missing(tmp_path, monkeypatch):
    """Errors report the original value, like ``resolve_path`` does."""
    monkeypatch.setenv("HOME", os.fspath(tmp_path))
    monkeypatch.setenv("USERPROFILE", os.fspath(tmp_path))

    with pytest.raises(click.BadParameter, match="'~/missing' does not exist"):
        click.Path(exists=True, expand_user=True).convert("~/missing", None, None)


def test_path_expand_user_default_off(tmp_path, monkeypatch):
    """By default ``~`` stays a literal path segment, for backwards
    compatibility."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.BadParameter, match="does not exist"):
        click.Path(exists=True).convert("~/file", None, None)


def _non_utf8_filenames_supported():
    with tempfile.TemporaryDirectory(prefix="click-pytest-") as tempdir:
        try:
            f = open(os.path.join(tempdir, "\udcff"), "w")
        except OSError:
            return False

        f.close()
        return True


@pytest.mark.skipif(
    not _non_utf8_filenames_supported(),
    reason="The current OS or FS doesn't support non-UTF-8 filenames.",
)
def test_path_surrogates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    type = click.Path(exists=True)
    path = pathlib.Path("\udcff")

    with pytest.raises(click.BadParameter, match="'�' does not exist"):
        type.convert(path, None, None)

    type = click.Path(file_okay=False)
    path.touch()

    with pytest.raises(click.BadParameter, match="'�' is a file"):
        type.convert(path, None, None)

    path.unlink()
    type = click.Path(dir_okay=False)
    path.mkdir()

    with pytest.raises(click.BadParameter, match="'�' is a directory"):
        type.convert(path, None, None)

    path.rmdir()

    def no_access(*args, **kwargs):
        """Test environments may be running as root, so we have to fake the result of
        the access tests that use os.access
        """
        p = args[0]
        assert p == path, f"unexpected os.access call on file not under test: {p!r}"
        return False

    path.touch()
    type = click.Path(readable=True)

    with pytest.raises(click.BadParameter, match="'�' is not readable"):
        with monkeypatch.context() as m:
            m.setattr(os, "access", no_access)
            type.convert(path, None, None)

    type = click.Path(readable=False, writable=True)

    with pytest.raises(click.BadParameter, match="'�' is not writable"):
        with monkeypatch.context() as m:
            m.setattr(os, "access", no_access)
            type.convert(path, None, None)

    type = click.Path(readable=False, executable=True)

    with pytest.raises(click.BadParameter, match="'�' is not executable"):
        with monkeypatch.context() as m:
            m.setattr(os, "access", no_access)
            type.convert(path, None, None)

    path.unlink()


def _non_utf8_filenames_supported():
    with tempfile.TemporaryDirectory(prefix="click-pytest-") as tempdir:
        try:
            f = open(os.path.join(tempdir, "\udcff"), "w")
        except OSError:
            return False

        f.close()
        return True


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Filepath syntax differences."
)
def test_invalid_path_with_esc_sequence():
    with pytest.raises(click.BadParameter) as exc_info:
        with tempfile.TemporaryDirectory(prefix="my\ndir") as tempdir:
            click.Path(dir_okay=False).convert(tempdir, None, None)

    assert "my\\ndir" in exc_info.value.message


@pytest.mark.parametrize(
    ("cls", "expect"),
    [
        (None, "a/b/c.txt"),
        (str, "a/b/c.txt"),
        (bytes, b"a/b/c.txt"),
        (pathlib.Path, pathlib.Path("a", "b", "c.txt")),
    ],
)
def test_path_type(runner, cls, expect):
    cli = click.Command(
        "cli",
        params=[click.Argument(["p"], type=click.Path(path_type=cls))],
        callback=lambda p: p,
    )
    result = runner.invoke(cli, ["a/b/c.txt"], standalone_mode=False)
    assert result.exception is None
    assert result.return_value == expect

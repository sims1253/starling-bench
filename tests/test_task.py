import subprocess
import tomllib

from starling_bench.task import prepare_task


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_task_exports_commit_not_working_tree(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "engine.cpp").write_text("committed")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    revision = git(repo, "rev-parse", "HEAD")
    (repo / "engine.cpp").write_text("uncommitted solution")
    (repo / "private.wav").write_bytes(b"private input")
    output = tmp_path / "task"
    prepare_task(repo, revision, output)
    exported = output / "environment" / "starling"
    assert (exported / "engine.cpp").read_text() == "committed"
    assert not (exported / ".git").exists()
    assert not (exported / "private.wav").exists()
    config = tomllib.loads((output / "task.toml").read_text())
    assert config["verifier"]["environment_mode"] == "separate"
    assert config["artifacts"][0]["destination"] == "submission"

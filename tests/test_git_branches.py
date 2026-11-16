import subprocess
from pathlib import Path

import git_branches as gb
import pytest


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-b", "main")
    (r / "a.txt").write_text("one\n")
    git(r, "add", ".")
    git(r, "commit", "-m", "first")
    return r


def code_of(exc_info):
    return exc_info.value.code


def test_list_branches_marks_the_current_and_default_branch(repo):
    git(repo, "branch", "feature")
    out = gb.list_branches(str(repo))
    assert out["current"] == "main" and out["default"] == "main"
    assert {b["name"] for b in out["local"]} == {"main", "feature"}
    assert [b["name"] for b in out["local"] if b["current"]] == ["main"]


def test_list_branches_includes_remote_only_branches(repo, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "origin", "main")
    git(repo, "branch", "topic")
    git(repo, "push", "origin", "topic")
    git(repo, "branch", "-D", "topic")
    out = gb.list_branches(str(repo))
    assert "origin/topic" in out["remote"] and "origin/HEAD" not in out["remote"]


def test_checkout_switches_branch(repo):
    git(repo, "branch", "feature")
    gb.checkout(str(repo), "feature")
    assert gb.list_branches(str(repo))["current"] == "feature"


def test_checkout_refuses_uncommitted_changes_until_confirmed(repo):
    git(repo, "branch", "feature")
    (repo / "a.txt").write_text("changed\n")
    with pytest.raises(gb.GitOpError) as e:
        gb.checkout(str(repo), "feature")
    assert code_of(e) == "dirty" and e.value.status == 409
    gb.checkout(str(repo), "feature", confirm_dirty=True)
    assert gb.list_branches(str(repo))["current"] == "feature"


def test_checkout_never_forces_over_a_conflicting_change(repo):
    git(repo, "checkout", "-b", "feature")
    (repo / "a.txt").write_text("feature\n")
    git(repo, "commit", "-am", "feature change")
    git(repo, "checkout", "main")
    (repo / "a.txt").write_text("local edit\n")
    with pytest.raises(gb.GitOpError) as e:
        gb.checkout(str(repo), "feature", confirm_dirty=True)
    assert e.value.status == 409
    assert (repo / "a.txt").read_text() == "local edit\n"


@pytest.mark.parametrize("name", ["-b", "--force", "a b", "bad..name", "", "x" * 300, "has~tilde"])
def test_branch_names_are_validated(repo, name):
    with pytest.raises(gb.GitOpError) as e:
        gb.checkout(str(repo), name)
    assert e.value.status == 400
    with pytest.raises(gb.GitOpError) as e:
        gb.create_branch(str(repo), name)
    assert e.value.status == 400


def test_checkout_unknown_branch_is_404(repo):
    with pytest.raises(gb.GitOpError) as e:
        gb.checkout(str(repo), "nope")
    assert e.value.status == 404


def test_create_branch_checks_it_out_and_refuses_duplicates(repo):
    gb.create_branch(str(repo), "feature/x")
    assert gb.list_branches(str(repo))["current"] == "feature/x"
    with pytest.raises(gb.GitOpError) as e:
        gb.create_branch(str(repo), "feature/x")
    assert e.value.status == 409


def test_delete_branch_refuses_current_default_and_unmerged(repo):
    with pytest.raises(gb.GitOpError) as e:
        gb.delete_branch(str(repo), "main")
    assert e.value.status == 409
    git(repo, "checkout", "-b", "feature")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "work")
    git(repo, "checkout", "-b", "other", "main")
    with pytest.raises(gb.GitOpError) as e:
        gb.delete_branch(str(repo), "feature")
    assert e.value.status == 409 and "not fully merged" in e.value.message.lower()
    with pytest.raises(gb.GitOpError) as e:
        gb.delete_branch(str(repo), "other")
    assert e.value.status == 409


def test_delete_merged_branch(repo):
    git(repo, "branch", "done")
    gb.delete_branch(str(repo), "done")
    assert "done" not in {b["name"] for b in gb.list_branches(str(repo))["local"]}


def test_list_worktrees_marks_the_main_folder(repo):
    out = gb.list_worktrees(str(repo))
    assert len(out) == 1 and out[0]["is_main"] and out[0]["branch"] == "main"


def test_add_worktree_creates_a_sibling_folder_for_a_new_branch(repo):
    made = gb.add_worktree(str(repo), "feature")
    path = Path(made["path"])
    assert path.is_dir() and path.parent.parent == repo.parent
    assert path.parent.name == "proj-worktrees"
    listed = gb.list_worktrees(str(repo))
    assert {w["branch"] for w in listed} == {"main", "feature"}
    assert [w for w in listed if w["branch"] == "feature"][0]["is_main"] is False


def test_add_worktree_for_an_existing_branch(repo):
    git(repo, "branch", "feature")
    made = gb.add_worktree(str(repo), "feature")
    assert gb.list_worktrees(str(repo))[1]["branch"] == "feature"
    assert Path(made["path"]).name == "feature"


def test_add_worktree_refuses_a_branch_checked_out_elsewhere(repo):
    with pytest.raises(gb.GitOpError) as e:
        gb.add_worktree(str(repo), "main")
    assert e.value.status == 409


def test_add_worktree_slugs_slashes_in_the_folder_name(repo):
    made = gb.add_worktree(str(repo), "feature/login")
    assert Path(made["path"]).name == "feature-login"


def test_remove_worktree_deletes_the_folder_but_keeps_the_branch(repo):
    made = gb.add_worktree(str(repo), "feature")
    gb.remove_worktree(str(repo), made["path"])
    assert not Path(made["path"]).exists()
    assert "feature" in {b["name"] for b in gb.list_branches(str(repo))["local"]}


def test_remove_worktree_refuses_the_main_folder_and_unknown_paths(repo, tmp_path):
    with pytest.raises(gb.GitOpError) as e:
        gb.remove_worktree(str(repo), str(repo))
    assert e.value.status == 409
    with pytest.raises(gb.GitOpError) as e:
        gb.remove_worktree(str(repo), str(tmp_path))
    assert e.value.status == 400


def test_remove_worktree_refuses_a_dirty_tree(repo):
    made = gb.add_worktree(str(repo), "feature")
    (Path(made["path"]) / "a.txt").write_text("dirty\n")
    with pytest.raises(gb.GitOpError) as e:
        gb.remove_worktree(str(repo), made["path"])
    assert e.value.status == 409 and Path(made["path"]).exists()
    assert "--force" not in e.value.message
    assert "uncommitted" in e.value.message


def test_resolve_worktree_accepts_listed_paths_only(repo, tmp_path):
    made = gb.add_worktree(str(repo), "feature")
    assert gb.resolve_worktree(str(repo), "") == str(repo)
    assert Path(gb.resolve_worktree(str(repo), made["path"])) == Path(made["path"])
    with pytest.raises(gb.GitOpError) as e:
        gb.resolve_worktree(str(repo), str(tmp_path))
    assert e.value.status == 400

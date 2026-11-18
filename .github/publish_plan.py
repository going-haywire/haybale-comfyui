"""Decide what publish.yml does. Standard library only; reads the checked-out project.

Writes ``enabled``, ``matrix``, ``standalone`` and ``tag`` to $GITHUB_OUTPUT. ``tag`` is set
only for a push to the default branch that changed the libraries' versions without a tag:
the workflow then creates it. Exits 1, with a message, when
publishing was requested but the run cannot be trusted to publish the right thing.
"""

import json
import os
import pathlib
import subprocess
import sys
import tomllib


def emit(enabled, matrix, standalone, tag=""):
    line = (
        f"enabled={'true' if enabled else 'false'}\n"
        f"matrix={json.dumps(matrix)}\n"
        f"standalone={'true' if standalone else 'false'}\n"
        f"tag={tag}\n"
    )
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a") as handle:
            handle.write(line)
    print(line, end="")


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


root = pathlib.Path(".")
config = tomllib.loads((root / "pyproject.toml").read_text())


def leaves_the_checkout(path):
    target = pathlib.Path(path)
    target = target if target.is_absolute() else root / target
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


# A root that links to something outside this checkout (a --dev project's haywire
# checkout) cannot be installed on a runner, so its tests cannot run there.
sources = config.get("tool", {}).get("uv", {}).get("sources", {})
standalone = not any(
    isinstance(source, dict) and "path" in source and leaves_the_checkout(source["path"])
    for source in sources.values()
)
distribute = config.get("tool", {}).get("haywire", {}).get("marketstall", {}).get("distribute", "git")

if distribute != "pypi":
    print(f"distribute = {distribute!r}: nothing to publish to PyPI.")
    emit(False, [], standalone)
    sys.exit(0)

ref_type = os.environ.get("GITHUB_REF_TYPE")
# A push to the default branch publishes when it changed the versions (a merged release PR).
on_default_branch = os.environ.get("GITHUB_EVENT_NAME") == "push" and ref_type == "branch"
if on_default_branch and os.environ.get("GITHUB_REF_NAME") != os.environ.get("DEFAULT_BRANCH"):
    print("A push to a branch other than the default branch: nothing to publish.")
    emit(False, [], standalone)
    sys.exit(0)
if ref_type != "tag" and not on_default_branch:
    fail("Publishing runs on a version tag only. Retry with: gh workflow run publish.yml --ref vX.Y.Z")

libraries = []
for directory in sorted((root / "barn").glob("*")):
    manifest = directory / "pyproject.toml"
    if directory.is_symlink() or not manifest.is_file():
        continue
    project = tomllib.loads(manifest.read_text())["project"]
    libraries.append({"dist": project["name"], "version": project["version"], "path": directory.as_posix()})

if not libraries:
    fail("No library under barn/ to publish.")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


if on_default_branch:
    versions = {item["version"] for item in libraries}
    before = os.environ.get("BEFORE_SHA", "")
    if len(versions) != 1 or not before.strip("0"):
        print("No single new version to release in this push.")
        emit(False, [], standalone)
        sys.exit(0)
    tag = f"v{versions.pop()}"
    earlier = set()
    for item in libraries:
        old = git("show", f"{before}:{item['path']}/pyproject.toml")
        if old.returncode == 0:
            earlier.add((item["dist"], tomllib.loads(old.stdout)["project"]["version"]))
    if earlier == {(item["dist"], item["version"]) for item in libraries}:
        print("The versions did not change in this push: nothing to release.")
        emit(False, [], standalone)
        sys.exit(0)
    if git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0:
        print(f"{tag} is already tagged: nothing to release.")
        emit(False, [], standalone)
        sys.exit(0)
    emit(True, libraries, standalone, tag)
    sys.exit(0)

tag = os.environ.get("GITHUB_REF_NAME", "")
wrong = [item for item in libraries if tag != f"v{item['version']}"]
if wrong:
    names = ", ".join(f"{item['dist']} {item['version']}" for item in wrong)
    fail(f"Tag {tag} does not match the committed version of: {names}. Nothing was uploaded.")

emit(True, libraries, standalone)

# Haybale Comfyui

A haywire project (`haybale-comfyui`): one haybale library under `barn/`, released with `haywire share`.

## Working in this repository

This is a going-haywire library and follows core's process: branches and pull requests,
CI before every merge, a protected `master`, releases through a release pull request. The
rules are in the org's [CONTRIBUTING.md](https://github.com/going-haywire/.github/blob/main/CONTRIBUTING.md)
and core's [CONTRIBUTING.md](https://github.com/going-haywire/haywire/blob/master/CONTRIBUTING.md);
the step-by-step is core's workflow page, which this repository's committed files bring
into every session: the Farmhand bridge (`.mcp.json`) serves it as
`farmhand://dev/collaboration/workflow.md`, and `.claude/settings.json` runs core's hooks
from `../haywire-repo/dev/hooks/`. Read it (or `../haywire-repo/docs/collaboration/workflow.md`)
before the first branch, commit, push or `gh pr` command of any task; the hooks refuse a
commit until this session has.

- **Layout.** This is a development project: `[tool.uv.sources]` reaches core at
  `../haywire-repo`, so this repository is cloned beside core. Its own environment runs its
  tests; the full studio with every library runs from the umbrella environment
  ([ADR 0081](https://github.com/going-haywire/haywire/blob/master/docs/adr/0081-libraries-from-other-repositories-run-from-an-umbrella-environment.md)).
  A worktree can be anywhere: its setup (t3.json's *Worktree setup*) links core beside it.
- **Checks** before each commit: `uv run --frozen ruff check .`, `uv run --frozen ruff
  format --check .`, `uv run --frozen pytest`. CI runs them against core's `master` on every
  pull request and every night.
- **Releases** go through a release pull request: `share --bump patch --pr` (the `READY`
  row below). Merging it is the owner's word, and the merge run tags and publishes.

## Releases

Release only with `haywire share`, from the project root. It bumps every version, writes
`marketstall.toml` and the README subscribe link, then commits, tags and pushes by itself.
A published version is permanent.

- Always `uv run --frozen`, so `uv` does not re-lock; if `uv.lock` changed unintentionally, `git checkout uv.lock`.
- Run `share --status` before acting, and again after any unclear result (a denial message, a timeout). The tool may have run.
- Never run `share --bump` twice for one change.
- Never tag, push tags, force-push, or edit versions, `install_spec` or `marketstall.toml` by hand.
- `STOP` means stop. Do not work around it.

`uv run --frozen haywire share --status` ends with a `STATE:` line. Act on it:

| `STATE:` | Meaning | You do |
|---|---|---|
| `READY` | Everything is in order. | Run `uv run --frozen haywire share --bump patch`. Use `minor` or `major` only if the owner said so. Add `--pr` when the default branch only accepts pull requests: it opens a release PR (`RELEASE_PR_OPEN`) instead of tagging. |
| `RELEASED` | This change is already released. | Nothing. Do not run `share` again. |
| `NOTHING_TO_RELEASE` | Nothing under `barn/` or the root `pyproject.toml` changed since the last release. | Nothing. Commit a change first if one was intended. |
| `BLOCKED` | A fixable problem stops the release. | Run the command on the `NEXT:` line, then `share --status` again. |
| `NEEDS_HUMAN` | Only the owner can proceed. | Paste the whole output, checklist included, to the owner and wait. Run the `THEN:` command only after they confirm. |
| `UNPUSHED` | A release commit exists that the remote does not have. | Run `uv run --frozen haywire share --resume` once. If it fails, stop and tell the owner. |
| `RELEASE_PR_OPEN` | A release PR is open and not merged. | Give the owner the PR link (the `PR:` line) and wait. Do not merge it, tag, or run `share` again. |
| `RELEASE_MERGED` | A release PR was merged and its version has no tag. | Pull the default branch, run `uv run --frozen haywire share --resume` once (it tags the merge commit and pushes the tag). If it fails, stop and tell the owner. |
| `STALE_MARKER` | An interrupted release does not match this checkout. | Stop and tell the owner. |
| `FAILED` | A step failed and its changes were reverted. | Read the error, fix its cause, run `share --status`. Do not retry in a loop. |
| `USAGE` | The command line was wrong. | Fix the command; see `share --help`. |
| `UNKNOWN` | Anything else. | Stop and paste the full output to the owner. |

- If a dependency pin needs a version that is not released yet, raise its floor as the
  release reminders section says, and ask the owner before releasing.
- Libraries named `hay-*` are local-only and `share` refuses them. Before any graph exists,
  the cheap fix is to create the project again with `haywire init <name> --distname
  haybale-<name>`; afterwards `haywire rename` rewrites every graph, and the owner chooses
  the name. Ask the owner for the name before sharing.
- Some steps only the owner can do: creating the GitHub repository, registering a PyPI
  pending publisher, creating the GitHub `pypi` environment. `share` prints them as a
  checklist after `STOP: human needed`. Paste that checklist to the owner verbatim and
  wait; never attempt them yourself.
- Never force-push, and never delete or move a tag.

## Release reminders

([sharing-libraries §7.1](https://github.com/going-haywire/haywire/blob/master/docs/guides/sharing-libraries.md#71-release-reminders))

A change that needs an unreleased change of a dependency raises that dependency's floor to the next patch after the dependency's latest release (`>=0.5.4` while PyPI has 0.5.3), in the same commit. `share` refuses to release while no PyPI release satisfies a floor, so the floor is the record of the wait.

A release reminder is an issue for a wait no floor can record: the change has no code yet, or the project develops against PyPI core. It is a help, not a rule: open one only when the owner agrees. Propose the issue to the owner: its title, the label, the steps, and for `after-core-release` a first line `Waits for: going-haywire/haywire@<sha> (#<pr>)`. Link a prepared branch's draft PR to it.

| Label | Meaning | Read |
|---|---|---|
| `todo-pre-release` | Something the owner decided to do before the next release of this project. | Before `haywire share`, `--dry-run` included: `gh issue list --label todo-pre-release --state open`. If any are open, list them and ask the owner whether to release anyway. |
| `after-core-release` | A dependency to raise once a released haywire-core contains the change on the issue's `Waits for:` line, when no floor can record the wait yet. | At the start of a session: `gh issue list --label after-core-release --state open`; check each one as below and tell the owner which can now be done. |

The change on a `Waits for:` line is released when the latest haywire-core on PyPI contains the commit:

```sh
v=$(curl -s https://pypi.org/pypi/haywire-core/json | jq -r .info.version)
gh api "repos/going-haywire/haywire/compare/v$v...<sha>" --jq .status  # behind or identical: released
```

Create the labels when the owner agrees to the first reminder (safe to repeat):

```sh
gh label create todo-pre-release --color D93F0B --description "Reminder: to do before the next release" --force
gh label create after-core-release --color FBCA04 --description "Reminder: to do once a haywire-core release contains the needed change" --force
```

If `gh` is missing or not logged in, or the repository is not on GitHub, tell the owner the reminders could not be read; never report that none are open.

## Live checks

A live check asks the owner to confirm in the running studio (`uv run haywire`) that a
change works. It costs their time: ask only for a change only a person can judge (UI,
interaction, a device), only once your own tests and checks leave you confident it works,
and only with the steps that need a person. With Farmhand connected, post those steps as a
Questionnaire (`haybale-studio_post_questionnaire`, format:
[questionnaire](https://github.com/going-haywire/haywire/blob/master/docs/reference/questionnaire.md)),
then read the answers with `haybale-studio_get_findings` once the owner says they are done.

## Where it publishes

`haywire init` sets no `distribute`, so the default is `git`: consumers install from your
repository's tag. `.github/workflows/publish.yml` is already in the project and does
nothing while `distribute` is `git`.

To publish to PyPI instead, set `distribute = "pypi"` under `[tool.haywire.marketstall]`
in the root `pyproject.toml` and follow
[docs/guides/publish-to-pypi.md](https://github.com/going-haywire/haywire/blob/master/docs/guides/publish-to-pypi.md).
The first PyPI release: a pending publisher does not make the name exist (PyPI answers 404),
so a plain `share` stops with `STOP: human needed` and a checklist for the owner. Once the
owner confirms they did it, run `uv run --frozen haywire share --first-release`; it tags the
current version and CI uploads it. Agents never tag or push tags by hand. From then on use
`share --bump patch` for every release.

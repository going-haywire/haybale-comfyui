# Haybale Comfyui

A haywire project (`haybale-comfyui`): one haybale library under `barn/`, released with `haywire share`.

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
| `READY` | Everything is in order. | Run `uv run --frozen haywire share --bump patch`. Use `minor` or `major` only if the owner said so. |
| `RELEASED` | This change is already released. | Nothing. Do not run `share` again. |
| `NOTHING_TO_RELEASE` | Nothing under `barn/` or the root `pyproject.toml` changed since the last release. | Nothing. Commit a change first if one was intended. |
| `BLOCKED` | A fixable problem stops the release. | Run the command on the `NEXT:` line, then `share --status` again. |
| `NEEDS_HUMAN` | Only the owner can proceed. | Paste the whole output, checklist included, to the owner and wait. Run the `THEN:` command only after they confirm. |
| `UNPUSHED` | A release commit exists that the remote does not have. | Run `uv run --frozen haywire share --resume` once. If it fails, stop and tell the owner. |
| `STALE_MARKER` | An interrupted release does not match this checkout. | Stop and tell the owner. |
| `FAILED` | A step failed and its changes were reverted. | Read the error, fix its cause, run `share --status`. Do not retry in a loop. |
| `USAGE` | The command line was wrong. | Fix the command; see `share --help`. |
| `UNKNOWN` | Anything else. | Stop and paste the full output to the owner. |

- If a dependency pin needs a version that is not released yet, stop and ask.
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

A release reminder is an issue that records a decision affecting the next release, so it is not forgotten. It is a help, not a rule: open one only when the owner agrees. When a change you make needs something done at release time (most often a dependency floor to raise once a release contains a change), propose the issue to the owner: its title, the label, the steps, and for `after-core-release` a first line `Waits for: going-haywire/haywire@<sha> (#<pr>)`. Link a prepared branch's draft PR to it.

| Label | Meaning | Read |
|---|---|---|
| `todo-pre-release` | Something the owner decided to do before the next release of this project. | Before `haywire share`, `--dry-run` included: `gh issue list --label todo-pre-release --state open`. If any are open, list them and ask the owner whether to release anyway. |
| `after-core-release` | A dependency to raise (usually the `haywire-core` floor) once a released haywire-core contains the change on the issue's `Waits for:` line. | At the start of a session: `gh issue list --label after-core-release --state open`; check each one as below and tell the owner which can now be done. |

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

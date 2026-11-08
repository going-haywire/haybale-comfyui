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

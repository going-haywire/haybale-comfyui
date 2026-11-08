# Haybale Comfyui

A haywire project.

## Subscribe

<!-- marketstall:share-url:start -->
```sh
*Subscribe URL not yet published — push this repo to a git remote, then run `uv run --frozen haywire share --bump patch`.*
```
<!-- marketstall:share-url:end -->

## Getting started

```sh
uv sync
uv run haywire
```
## Share your library

`haywire share` releases the project: it bumps every file to the version, writes
`marketstall.toml`, updates the subscribe link above, then **commits, tags and
pushes by itself**. Run it from the project root with a clean working tree
(`git checkout uv.lock` first if `uv` re-locked it). The version is an explicit
`x.y.z` or `major`/`minor`/`patch`. Look first, then release:
```sh
uv run --frozen haywire share --dry-run
uv run --frozen haywire share --bump patch
```

See [CLAUDE.md](CLAUDE.md) for the release rules.

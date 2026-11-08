# haybale-comfyui: design note (v1)

Status: draft for owner review. Written 2026-11-08. Docs only, no node code yet.
Legend: **[V]** verified this session (fetched docs or run), **[I]** inferred or from memory.

Goal: a very small node set that sends text (and optionally an image) to a *running* ComfyUI
server and returns images, with progress and cancel. No torch, no model handling: the heavy work
happens in ComfyUI. Sibling project `haybale-diffusion` (native diffusers nodes) is separate and
not affected.

## 1. Prior art (what other bridges do)

| Tool | Pattern | Lesson |
|---|---|---|
| ComfyUI's own example scripts | POST `/prompt`, wait on `/ws`, then read `/history/{id}` and fetch `/view` (a third example streams binary frames via a `SaveImageWebsocket` node) [V] (docs.comfy.org api-examples, via search summary) | Wait on the WebSocket, then read history; do not poll blindly |
| Krita AI Diffusion | Connects to a local or remote server by URL; **requires custom node packs installed on the server** (ControlNet preprocessors, IP-Adapter) [V via search summary] | Server-side helpers are accepted practice, but they raise the install burden |
| n8n community node | Sends a workflow JSON to the API; reported to break when the ComfyUI workflow changes [V via search summary] | Hard-wired node ids are the fragile part; address inputs by something stable |
| comfyui-mcp and Rust/Python clients | Thin wrappers over `/prompt`, `/history`, `/view`, `/upload/image`, `/ws` [V via search summary] | The wire protocol is small; no need for a big client |

Not looked at in depth: the source of these projects (search summaries only). Worth reading
Krita AI Diffusion's server client before step 2, but it is GPL-3.0 as far as I know **[I]**, so
description only, no copying.

## 2. The ComfyUI API we rely on

From the ComfyUI route listing **[V]**: `POST /prompt` (returns `prompt_id`, `number`, or `error` +
`node_errors`), `GET /history/{prompt_id}`, `GET /view`, `POST /upload/image`, `GET /object_info`,
`GET /queue`, `POST /interrupt`, `POST /free`, `GET /system_stats`, WebSocket `/ws` with messages
`status`, `execution_start`, `execution_cached`, `executing`, `progress`, `executed`.

The docs page lists routes but gives **no payload fields and no auth description [V]**. Payload
shapes (client_id in the websocket URL and the prompt body, `progress` carrying value/max, the
`images` entries in history outputs with filename/subfolder/type) are from my memory **[I]** and must
be checked against a live server first thing (step 0 below).

## 3. Node set (kept small: one node)

Library setting **ComfyUI** (like spandrel's settings): server URL (default `http://127.0.0.1:8188`),
optional auth header name/value (stored as a secret if the framework has one, otherwise flagged for
the owner), timeout, "free models after run".

| Node | Inlets | Config | Outlets |
|---|---|---|---|
| **ComfyUI Workflow** | `image` (optional IMAGE), dynamic inlets from the workflow (below) | workflow file (API-format JSON), seed behaviour (fixed/randomize), output pick | `image` IMAGE (and extra outlets if the workflow has several outputs) |
| ~~ComfyUI Text to Image~~ | dropped from v1, see §6 | | |

One node plus the settings (Text to Image deferred, §6). Deliberately **no** KSampler-style granular nodes: that would be a
second graph engine.

### 3.1 How a generic workflow becomes ports (no server pack needed)

A user exports *Save (API Format)* from ComfyUI. The node reads the JSON and builds ports from
a **title convention** (my proposal, not from the prior art **[I]**): any node whose `_meta.title`
starts with `hw:` exposes its widget inputs as inlets named by the rest of the title, e.g. a
CLIPTextEncode titled `hw:prompt` gives inlet `prompt`; a LoadImage titled `hw:image` gives an
IMAGE inlet; `SaveImage` / `PreviewImage` nodes give IMAGE outlets. Ids can change on re-export,
titles do not, which addresses the fragility reported for n8n. A workflow without any `hw:` title
still runs, with a "pick inputs" card listing candidate widgets.

### 3.2 Run flow

1. Resolve settings; check server (`/system_stats`), unreachable gives a card warning, not a crash.
2. Upload IMAGE inlets (`/upload/image`), patch the workflow copy (values from inlets, seed).
3. `POST /prompt`; on `node_errors` show them on the card, per ComfyUI node.
4. Listen on `/ws` filtered by our `prompt_id`; map `progress` to the node's progress bar,
   `execution_cached` to a "cached" note. Honour `context.cancel` by `POST /interrupt` (+ delete from queue).
5. On completion read `/history/{id}`, fetch images from `/view`, decode to `ImageValue`
   (numpy via `ImageValue.from_array` [V exists in haybale-image], reusing the spandrel progress/cancel
   pattern [V from the diffusion design note]).

Type design is trivial: only STRING/INT/FLOAT/IMAGE cross wires, so no new wire types, nothing to
keep out of saved graphs except the server secret.

Dependencies: `httpx` (already a haybale-models dependency [V]) and a websocket client (`websockets`
or `httpx-ws`). No torch.

## 4. Optional server-side pack (your question)

A small ComfyUI custom node pack, `comfyui-haywire`, installed into `ComfyUI/custom_nodes`:

- **Input/Output marker nodes** (`HaywireText`, `HaywireImage`, `HaywireSeed`, `HaywireOutput`): typed,
  named, stable. They replace the `hw:` title convention with a real contract and let the pack
  advertise a workflow's ports in one call.
- **A custom route**, e.g. `GET /haywire/ports/{workflow}` and a single `POST /haywire/run` that takes named
  inputs and returns when done; ComfyUI allows extensions to add routes (the docs' own example
  client uses a custom route [V]).
- **Efficient image return**: stream binary frames over `/ws` instead of write-then-fetch, useful
  on remote or slow-disk servers.

Honest cost/benefit: it adds an install step on the server and a second package to version, and
the bridge already works without it through titles. It pays off for remote/cloud servers and for
teams sharing workflows. Licensing: a pack that imports ComfyUI modules is probably a derivative of
GPL-3.0 code **[I, not legal advice]**; keep it GPL-3.0 and keep haybale-comfyui (MIT) talking to it
only over HTTP. Recommendation: **ship the bridge first; build the pack only if the title
convention proves too weak.** Keep the wire protocol versioned so either end can detect the other.

## 5. Order of steps

0. Spike against a live ComfyUI (needs the owner's server URL, or install one): confirm every payload
   shape in §2 and what `/view` returns; capture sample JSON as test fixtures.
1. Packaging: dependencies, `haybale.toml`, library settings (URL, header, timeout).
2. `runtime/client.py`: small async-free client (httpx + ws), unit tests against a fake server.
3. `runtime/workflow.py`: parse API JSON, `hw:` convention, patch, validate; pure functions, fully tested.
4. **ComfyUI Workflow** node with dynamic ports, progress, cancel.
5. One example workflow in `examples/`.
6. Docs and example graph. Pack (§4) only afterwards.

## 6. Decisions so far (owner, 2026-11-08) and what is still open

Decided: library licence MIT, a future server pack GPL-3.0 (§4). No test server yet.

**Secrets (checked in haywire-repo).** There is no secret or credential setting type for libraries
[V: searched `core/settings` and `barn`; the only hits are the studio's own login/token system, which
does not apply]. What exists: `LibrarySettings` are plain files (`~/.haywire/settings.toml` and
`<workspace>/.haywire/settings.toml` per `setting-canon.md`; the persistence code I read writes
JSON, so the docs and code disagree on format, not verified further), and `TextWidget` has a
`password=True` option that only masks the field on screen [V]. The workspace file can end up in git,
and node settings are saved inside graph files, so a secret must not live in either by default.
Proposal: the library setting stores the **name of an environment variable** that holds the auth value
(for example `COMFYUI_AUTH`), read at run time; a plain-value field exists but shows a card warning
that it is saved in clear text. Ask the framework owners whether a real secret setting is planned.

**Bundled templates.** They only exist to serve the Text to Image node, so users can type a prompt
without first exporting a workflow from ComfyUI. The cost: each template hard-codes a checkpoint and
node classes, which differ per server, so it breaks on any server that lacks that model. Proposal:
**drop the Text to Image node and templates from v1.** One node, ComfyUI Workflow, plus one example
workflow file in `examples/` (documented, not a node) that users adapt. Add templates later if people
ask, built from `/object_info` so the checkpoint name comes from the server.

Still open: a ComfyUI server to test against (step 0 needs it); whether the `hw:` title convention
(§3.1) is acceptable or you prefer a different marker.

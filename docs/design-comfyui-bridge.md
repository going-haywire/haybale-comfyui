# haybale-comfyui: design note (v2)

Status: draft for owner review. Rewritten 2026-11-08; replaces v1 (the `hw:` title convention and
patching exported API JSON by node id are dropped). Docs only, no node code yet.

Legend:
**[V]** verified in this session (haywire source and docs read, GitHub API, or upstream source fetched);
**[S]** read from upstream source by the haybale-diffusion session and passed on in the brief,
not re-read here;
**[I]** inferred or from memory, to be confirmed in the spike (§8 step 0).

Goal: one haywire node that runs a workflow on a *running* ComfyUI server and returns its images,
with progress and cancel. No torch, no model handling: the heavy work happens in ComfyUI. The
sibling project `haybale-diffusion` (native diffusers nodes) is separate and not affected.

## 1. Decisions (owner, 2026-11-08)

- **One node**, *ComfyUI Workflow*. No Text-to-Image node and no bundled templates in v1.
- **Library settings**: server URL, the *name of an environment variable* that holds an auth
  header value, timeout (§6).
- **Licences**: haybale-comfyui is MIT. Any ComfyUI-side pack is GPL-3.0 and is only spoken to
  over HTTP/WebSocket; no ComfyUI or GPL code is imported or copied into this library.
- **Client**: our own thin client on `httpx` plus a websocket client. Not the official
  `comfy-sdk` (MIT, v0.5.0): it talks to Comfy-Org/comfy-api-proxy, which a self-hosted ComfyUI
  would need in front of it. Not the community clients: they use the export-and-patch pattern we
  dropped.
- **No test server yet.** The first implementation step is a spike against a live ComfyUI.

## 2. The pattern: placeholder nodes + live workflow exchange

The user builds the workflow in ComfyUI's own editor and marks what haywire should drive with
**placeholder nodes**: a parameter, an image input, an output. Inside ComfyUI the placeholders
return dummy values, so the workflow still runs there as usual. A small server-side extension
**publishes** the workflow (API format) to subscribed clients every time the graph changes. The
haywire node subscribes, reads the placeholders, builds its ports from them, and at run time
replaces each placeholder with the real value before submitting the graph.

This is the pattern Krita AI Diffusion uses for its custom-workflow mode. Compared with v1's
export-and-patch, it needs no export step, no node ids and no title convention, and the ports have
real types, defaults and ranges.

### 2.1 How Krita AI Diffusion does it (description only; both repos GPL-3.0)

Server side, `Acly/comfyui-tooling-nodes` (custom node pack):

- `krita.py` defines the placeholder nodes **[S]**:
  - `ETN_Parameter`: inputs `name`, `type` (auto, number, number (integer), toggle, choice,
    text, prompt (positive), prompt (negative)), `default`, `min`, `max`; one output `value`.
  - `ETN_KritaImageLayer` (`name` → image, mask), `ETN_KritaMaskLayer`, `ETN_KritaCanvas`
    (image, width, height, seed, mask), `ETN_KritaSelection`, `ETN_KritaStyle`, `ETN_KritaSendText`.
  - `ETN_KritaOutput`: an output node; sends PNGs over the client's websocket and adds an info
    dict (name, offset, batch mode).
  - In ComfyUI they all return dummy values, so the workflow runs in ComfyUI's UI too.
- `api.py` holds a workflow exchange with three routes **[V: route decorators read]**:
  `POST /api/etn/workflow/publish` `{name, client_id, workflow}`,
  `POST /api/etn/workflow/subscribe` `{client_id}`, `POST /api/etn/workflow/unsubscribe`
  `{client_id}`. Subscribers receive a websocket JSON message `etn_workflow_published`
  `{publisher: {name, id}, workflow}` **[S]**.
- `js/external_tooling_nodes.js`: when the graph contains an `ETN_KritaOutput`, every
  `graphChanged` event converts the graph to API format (`app.graphToPrompt()`) and posts it to
  the publish route **[S]**.
- The pack's README documents neither the Krita nodes nor the workflow routes: this is Krita's
  internal protocol, with no stability promise **[S]**.

Client side, `Acly/krita-ai-diffusion` **[S]**:

- `ai_diffusion/model/custom_workflow.py`, `workflow_parameters()`: turns the placeholder nodes of
  a received workflow into UI controls.
- `ai_diffusion/backend/workflow.py`, `expand_custom()` (about 80 lines): rewrites the graph before
  submit. A parameter becomes its literal value at every input that referenced it; an image layer
  becomes a base64 image loader; every other node is copied with its inputs remapped.
- `ai_diffusion/backend/comfy_workflow.py`, `_convert_ui_workflow()`: converts a normally saved
  (UI-format) workflow file into API format with the help of `/object_info`, so saved files work
  without the publish route.

Images in and out go through two pack nodes, "Load Image (Base64)" and "Send Image (WebSocket)".
The binary websocket frame is two big-endian uint32 (event type 1, format 2 = PNG) followed by the
PNG bytes; an `executed` JSON message with `node` and `prompt_id` follows **[S]** (the pack
imports `BinaryEventTypes` from ComfyUI's `server` module **[V]**).

## 3. The ComfyUI API we rely on

From the ComfyUI route listing **[V, v1 session]**: `POST /prompt` (returns `prompt_id`, `number`,
or `error` + `node_errors`), `GET /history/{prompt_id}`, `GET /view`, `POST /upload/image`,
`GET /object_info`, `GET /queue`, `POST /interrupt`, `POST /free`, `GET /system_stats`, and the
WebSocket `/ws` with messages `status`, `execution_start`, `execution_cached`, `executing`,
`progress`, `executed`. The docs list routes but give no payload fields and no auth description.

Plus the exchange routes of §2.1 (Option A) or our own (Option B, §5).

### 3.1 Spike results, part 1: the core protocol **[V]**

Run 2026-11-08 against the owner's local server (ComfyUI 0.44.0, torch 2.14.1+cu126, one
GTX 1080 Ti) with a 6-step SD1.5 workflow ending in `SaveImageWebsocket`. Scripts and captured
messages: `spike/` (`spike_core.py`, `spike_err.py`, `fixtures/*.json`).

- **Connect**: `ws://host/ws?clientId=<uuid>`; the first message is `status` with `sid` (= our id).
- **Submit**: `POST /prompt {prompt, client_id}` → 200 `{prompt_id, number, node_errors: {}}`.
  A validation failure → **400** `{error: {type, message, …}, node_errors: {<node id>: {errors:
  [{type, message, details, extra_info: {input_name, received_value, …}}], dependent_outputs,
  class_type}}}`: enough to name the bad input on the card.
- **Messages per run**, in order: `execution_start`, `execution_cached {nodes: [...]}`, then per
  node `executing {node, display_node, prompt_id}` and many `progress_state {prompt_id, nodes:
  {id: {value, max, state}}}`; the sampler sends `progress {value, max, prompt_id, node}`; the
  run ends with **`execution_success`** (plus a trailing `executing {node: null}`). Every message
  carries `prompt_id`. `progress_state` and `execution_success` are newer than the v1 route list.
- **Images**: `SaveImageWebsocket` sends a binary frame `>II (1, 2)` + PNG bytes (512×512 RGB,
  ~360 kB), with **no `executed` message after it**; it arrives between `executing` for the save
  node and `execution_success` of the same prompt. `/history/{id}` has empty `outputs` for it.
  `SaveImageWebsocket` is not core: it is `custom_nodes/websocket_image_save.py`, an example node
  tracked in ComfyUI's own repo, so it is present on a git install but can be removed.
- **Caching**: an identical second prompt reports nodes 1–6 in `execution_cached` and finishes in
  ~40 ms, but the websocket save node **runs again and resends the image**. So the cache question
  of §9 is settled for this output node; still to check for Acly's output node.
- **Cancel**: `POST /interrupt {prompt_id}` → 200; the run ends with `execution_interrupted
  {prompt_id, node_id, node_type, executed}` and no image.

### 3.2 Spike results, part 2: placeholders with comfyui-tooling-nodes 3.4.0 **[V]**

Same server, after the owner installed `comfyui-tooling-nodes` (commit `0abe742`, "Version
3.4.0"). Script `spike/spike_placeholders.py`, log `spike/fixtures/placeholder_log.json`. An
img2img workflow with three `ETN_Parameter` (prompt, strength, seed), one `ETN_KritaImageLayer`
and one `ETN_KritaOutput` named "Result".

- **Exchange**: subscribe, publish and unsubscribe each answer 200 `{"status": "success"}`. A
  publish reaches the subscriber as `etn_workflow_published {publisher: {name, id}, workflow}`
  with the workflow unchanged. The script published itself, standing in for the browser; what
  ComfyUI's own frontend sends on `graphChanged` is **not yet seen** (§8 step 0).
- **`/object_info`** confirms the placeholder inputs: `ETN_Parameter` has `name`, `type` (COMBO
  of the eight types), `default` (always a STRING), optional `min`/`max` (FLOAT), output `*`;
  `ETN_KritaImageLayer` has `name` → `image`, `mask`; `ETN_KritaOutput` has `images`, `x`, `y`,
  `name`, `batch_mode`, `resize_canvas`. `ETN_LoadImageBase64` takes `image` (STRING, base64 PNG)
  → `image`, `mask`. So the mapping table can read port defaults and ranges from the workflow
  itself; `default` must be parsed per type.
- **Unrewritten**, the placeholder workflow runs in ComfyUI as is (dummy values), as expected.
- **Rewritten** (parameter → literal, image layer → `ETN_LoadImageBase64` under the same node id,
  so downstream links stay valid): runs; the result keeps the input image's composition.
- **Output**: `ETN_KritaOutput` sends the binary PNG frame and then **`executed {node, output:
  {images: [{source: "websocket"}], info: [{name, offset_x, offset_y, batch_mode,
  resize_canvas}]}, prompt_id}`**. The `info.name` gives the outlet a frame belongs to.
- **Caching, the important one**: an identical second prompt reports *every* node cached,
  including `ETN_KritaOutput`, replays its `executed` message, and sends **no image frame**.
  (`SaveImageWebsocket` in §3.1 re-ran instead.) So the haywire node must either keep the last
  images per submitted-graph hash in `self.cache` and reuse them when `executed` arrives without
  frames, or make the output node always run. The second fails for a cache hit left by another
  client or a restarted haywire, so the node needs both: reuse when it can, and otherwise resubmit
  once with an always-run output. In Option B our output node should declare itself never cached
  (ComfyUI's `IS_CHANGED` hook **[I]**), which removes the problem at the source.

### 3.3 Spike results, part 3: a publish from ComfyUI's own frontend **[V]**

The owner edited a workflow in the browser while `spike/listen_publish.py` was subscribed
(fixture `spike/fixtures/browser_publish.json`, 7 messages).

- **Subscribe replays**: the first message was the workflow the spike had published *before*
  this subscription. So a new subscriber gets what is already published and need not wait for
  an edit.
- **Publisher**: `{name: "ComfyUI Web", id: <32 hex chars>}`. The id is per browser client
  (tab); the name is the same for every tab, and **the workflow's file name is not sent**. A
  picker must key on the publisher id and has no good label: an open point for Option B, whose
  JS can send the workflow name.
- **Format**: API format, as `graphToPrompt` produces it, with `_meta.title` (and `cnr_id`, `ver`
  from the saved file) on each node. **Subgraphs arrive flattened**, with path ids such as
  `74:62`; ids are strings and must not be parsed as numbers.
- **Every edit republishes the whole workflow**, also while it is incomplete: one publish had
  `ETN_KritaOutput` with its required `images` input missing. The node must validate a publish
  (does every required input exist?) before offering it, and should not rebuild ports on each
  keystroke: offer the update, as §4.2 already says.
- **Connection drop**: after a few minutes the websocket closed without a close frame while the
  server stayed up. Cause not found **[I: idle/ping timeout or a frontend reload]**. The client
  must reconnect and subscribe again; whether a subscription outlives its websocket is not
  checked.

## 4. The haywire node: ComfyUI Workflow

| | |
|---|---|
| Config | workflow picker (published workflows, plus "load file…" for a saved UI- or API-format JSON) |
| Inlets | built from the placeholders (§4.1); none until a workflow is picked |
| Outlets | one `IMAGE` per output placeholder, named after it |
| Card | progress bar; warnings for unreachable server, missing workflow, ComfyUI `node_errors` |

### 4.1 Placeholders to ports

A small **mapping table** (placeholder class → port factory) is the only place that knows the
server pack's names, so switching from Option A to B (§5) is a table change:

| Placeholder | Haywire port |
|---|---|
| Parameter, type number | `FLOAT` inlet with default, min, max |
| Parameter, type number (integer) | `INT` inlet |
| Parameter, type toggle | `BOOL` inlet |
| Parameter, type choice | `CHOICES` inlet (options from the placeholder) |
| Parameter, type text / prompt (positive / negative) | `STRING` inlet |
| Parameter, type auto | resolved from the input it feeds, via `/object_info` **[I]** |
| Image placeholder (A: `ETN_KritaImageLayer`, `ETN_KritaCanvas`'s image) | `IMAGE` inlet |
| Output node (A: `ETN_KritaOutput`) | `IMAGE` outlet per output name |
| Anything else (A: selection, style, send-text) | not supported in v1; card warning names it |

Port ids are derived from the placeholder **name** (not the ComfyUI node id), so re-publishing an
edited workflow keeps edges. The rebuild uses `with self.rejig(exclude=[PortOrigin.DECLARED])`:
ports re-added under the same id keep their edges, the rest are removed **[V: node-canon §7]**.
The rebuild runs in the picker's `on_change` handler, which may run while `worker()` runs, so the
shared workflow state is guarded by the node's own lock **[V: node-canon §6, threading contract]**.

### 4.2 Where the workflow lives

The chosen API-format JSON is kept in **`self.store`** (plain dicts and lists; carried by save,
copy and undo **[V: node-canon §5, NodeStore]**), so a saved graph runs without ComfyUI's UI open
and without a publish having happened in this session. A newer publish of the same name is
offered on the card ("workflow changed on server: update"), never applied silently, because it can
change the ports. Parsed placeholders and the mapping result are rebuilt in `post_init()`; decoded
images and the last `prompt_id` go in **`self.cache`** (never saved).

Cost: the workflow JSON is saved inside the graph file (tens of kB for a typical workflow **[I]**).

### 4.3 Run flow

1. `on_startup`: resolve library settings and the auth value from the environment; open the
   websocket (`/ws?clientId=…`) and subscribe. Unreachable server → card warning, not a crash.
2. `worker`: rewrite the stored graph: each Parameter placeholder becomes its inlet's literal value
   at every input that referenced it; each image placeholder becomes a base64 image loader
   carrying the inlet's PNG (`ImageValue.array()` → PNG via Pillow, already a haybale-image
   dependency **[V]**); everything else is copied with inputs remapped.
3. `POST /prompt` with our `client_id`; on `node_errors` show them on the card, per ComfyUI node.
4. Follow the websocket for our `prompt_id`: `progress` → `self.progress.busy(...)` span
   (`ProgressSettings` / `progress_field` **[V: setting-canon §3d]**); `execution_cached` → note.
   Poll `context.cancel` **[V: spandrel pattern]**; on cancel `POST /interrupt` (and remove the
   prompt from the queue if it has not started), then return without writing outlets.
5. Binary image frames → PNG decode → `ImageValue.from_array` **[V]** → outlet per output name.
6. `on_shutdown`: unsubscribe, close the websocket.

Wire types are only STRING / INT / FLOAT / BOOL / CHOICES / IMAGE: no new types.
Dependencies: `httpx`, a websocket client (`websockets` or `httpx-ws`), `haybale-image`. No torch.

## 5. Server side: Option A vs Option B

**Option A, spike: reuse Acly's comfyui-tooling-nodes as they are.**
Zero server code. But: Krita-branded node names; an undocumented protocol that can change for
Krita's needs; a workflow is only published when it contains an `ETN_KritaOutput`; and our
workflows also show up in Krita.

**Option B, before release: our own pack `comfyui-haywire` (GPL-3.0).**
Same design, our names and a documented, versioned contract: nodes *Haywire Parameter*,
*Haywire Image*, *Haywire Output*; a publish/subscribe route pair; a small JS hook that publishes
on graph change when a Haywire Output is present. Estimate about 200 lines of Python and 30 of JS.
Written from this description, not from Acly's code. Adds an install step on the server.

**Recommendation:** A for the spike, B before the first release. The haywire side keeps the
placeholder names in the one mapping table (§4.1), so A → B changes that table and the route
prefix, nothing else.

## 6. Settings and secrets

Library setting **ComfyUI** (pattern: `SpandrelSettings` + a `Barns` settings panel
**[V: haybale-spandrel]**):

| Field | Default |
|---|---|
| Server URL | `http://127.0.0.1:8188` |
| Auth environment variable | empty (no auth); e.g. `COMFYUI_AUTH` |
| Timeout (s) | 30 for HTTP calls; the run itself waits until done or cancelled |

There is no secret setting type for libraries **[V: searched `core/settings` and `barn`; the only
hits are the studio's own login system]**. `LibrarySettings` are plain files
(`~/.haywire/settings.toml` and `<workspace>/.haywire/settings.toml` per `setting-canon.md`), the
workspace file can end up in git, and node settings are saved inside graph files. So the setting
stores only the **name** of an environment variable, read at run time; the value never touches a
haywire file. `TextWidget(password=True)` only masks on screen **[V]** and is not used. Ask the
framework owners whether a real secret setting is planned.

## 7. Prior art

Licence and last push checked via the GitHub API on 2026-11-08 **[S]**.

| Project | Licence | Last push | Pattern | Use for us |
|---|---|---|---|---|
| Acly/krita-ai-diffusion (10.8k stars) | GPL-3.0 | 2026-11-06 | placeholder nodes + live exchange (§2.1) | the model for this design; description only |
| Acly/comfyui-tooling-nodes | GPL-3.0 | 2026-10-04 | server half of the above | Option A for the spike |
| ComfyUI-TD | AGPL-3.0 | 2026-08-20 | TouchDesigner-only push nodes | not reusable |
| TDComfyUI | none | 2025-01-09 | stale | no licence: do not read for reuse |
| n8n-nodes-comfyui | MIT | 2026-03-08 | export + patch by node id | the fragility we avoid |
| comfy-python-sdk (official) | MIT | 2026-11-07 | client for comfy-api-proxy | not for self-hosted servers |
| SethRobinson/comfyui-workflow-to-api-converter-endpoint | Unlicense | 2026-03-16 | server route converting UI → API format | reference for loading saved UI-format files |

## 8. Order of small PRs

0. **Spike**: done (§3.1–§3.3). Original plan: subscribe, receive one published
   workflow, rewrite one Parameter and one image placeholder, `POST /prompt`, receive progress and
   one PNG frame. Capture every message as a test fixture. Settles the **[I]** and **[S]** marks.
1. Packaging: dependencies, `haybale.toml`, library settings + panel.
2. `runtime/client.py`: HTTP + websocket client, tested against the spike fixtures.
3. `runtime/placeholders.py`: the mapping table, placeholder parsing, graph rewrite; pure
   functions, fully tested.
4. **ComfyUI Workflow** node: picker, dynamic ports, store, progress, cancel.
5. Loading saved files: API format first, then UI format via `/object_info`.
6. Option B: the `comfyui-haywire` pack (separate GPL-3.0 repo) and the table switch.
7. Docs and an example graph.

## 9. Open questions

- **Concurrency**: one server, several haywire nodes (or graphs). One websocket per node, or one
  shared client per server URL that routes messages? A shared client is likely needed **[I]**.
- **Routing images by `prompt_id`**: binary frames carry no prompt id. With `SaveImageWebsocket`
  no `executed` follows (§3.1); a frame belongs to the prompt of the last `executing` message.
  That holds as long as the server runs one prompt at a time **[I: ComfyUI's single queue
  worker]**; the output name per frame (several outputs) needs Acly's info dict or our own.
- **ComfyUI input caching**: settled (§3.1, §3.2): `SaveImageWebsocket` re-sends,
  `ETN_KritaOutput` does not. How to force a re-run under Option A without changing the
  workflow's result is still open (a re-run with a harmless changed input, or switching the
  output to `SaveImageWebsocket` in the rewrite, which loses `info.name`).
- **Auth**: which header? A plain ComfyUI has none; reverse proxies use `Authorization: Bearer …`
  or basic auth **[I]**. The setting holds a full header value; the header name may need a field.
- **ComfyUI version pinning**: minimum ComfyUI and tooling-nodes / comfyui-haywire versions; how
  the client detects a mismatch (`/system_stats`, a version route in Option B).
- **Placeholder type `auto`** and the **Krita-only placeholders** (selection, style, send-text):
  support later or never?

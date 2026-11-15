> Archived 2026-11-14 from the abandoned local repo haybale-diffusion (branch design/diffusion-node-set, commit d3c1af6). The project moved to the ComfyUI route; kept for the torch/Pascal (sm_61) and haybale-models findings in section 0.

# haybale-diffusion: design note (v1 node set)

Status: draft for owner review. Docs only, no node code yet. Written 2026-11-08.

Legend: **[V]** verified in this session (code read, command run, or model card fetched).
**[I]** inferred or from general knowledge, not verified here. Treat [I] as a hypothesis to test.

Clean-room rule: ComfyUI is GPL-3.0. Its node decomposition is design inspiration only. No ComfyUI
code or text is copied, and the ComfyUI source was **not** re-read for this note: the memory-management
section is written from general knowledge of how it behaves **[I]**. Implementation builds on
`diffusers` (Apache-2.0), `transformers` and `huggingface_hub`.

---

## 0. Findings that change the plan

1. **Pascal is not covered by the current default torch wheel. [V]**
   `../haybale-spandrel/.venv` has `torch 2.15.0+cu132`, `torch.cuda.is_available()` is `True`, but
   `torch.cuda.get_arch_list()` is `['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']`. A 1080 Ti is
   sm_61. `is_available()` says True and then kernels fail. The PyTorch notice says 2.14 is the last
   release with prebuilt CUDA 12.x wheels and Pascal support, and 2.15 drops them (it names sm_60, not
   sm_61 explicitly; the 2.15 arch list above settles it for us). `torch==2.14.1+cu126` exists on
   `download.pytorch.org/whl/cu126` for cp312 manylinux x86_64 **[V]**.
   Consequence: on the dev machine the library needs `torch<=2.14` from the cu126 index, and its device
   code must check arch support, not just `is_available()`.
2. **The stack resolves together. [V]** `uv pip compile` with `diffusers`, `transformers`, `accelerate`,
   `safetensors` and `huggingface_hub>=2.4` (the pin haybale-models carries) gives diffusers 0.42.1,
   transformers 5.22.2, huggingface-hub 2.4.0. No conflict at resolve time. Runtime behaviour is not tested.
3. **`PooledType` is not a resource pool. [V]** It is an inlet-only collection type (`dict[node_id, T]`).
   The model pool we need already exists: `haybale_models.pool.LoadedModels` (refcounted, keyed).
4. **Whole-repo `hf://org/repo@<commit>` addresses exist in haybale-models** and resolve to the HF
   snapshot folder. That is exactly what diffusers `from_pretrained(folder)` wants. **[V]** (guide
   `docs/guides/model-catalogs.md` §2.2, `haybale_models/hf.py`).

---

## 1. How the sibling libraries handle heavy ML deps

Sources read: `../haybale-spandrel` (closest match, torch, GPU), `../haybale-visiongraph` (OpenVINO/ONNX,
camera loops), `haywire-repo/barn/haybale-models` (catalog, downloads, pool).

| Concern | spandrel | visiongraph | Verdict for diffusion |
|---|---|---|---|
| torch dependency | plain `"torch"` in `dependencies` (no extras) [V] | no torch; `visiongraph[onnx,openvino,...]` [V] | spandrel's is not enough for us, see §6 |
| lazy import | `import torch` inside functions, `TYPE_CHECKING` only at module top [V] (`runtime/devices.py`) | n/a | **copy**: library must import and list nodes without torch loaded |
| device pick | `resolve_device(name)`: auto = cuda, then mps, then cpu; `cuda:N` accepted; unavailable device falls back to cpu **with a note** [V] | OpenVINO device string setting [V] | **copy**, then extend (arch check, §5) |
| dtype pick | `resolve_dtype(precision, device, supports_half, supports_bfloat16)`, notes on fallback [V] | n/a | **copy shape**, rewrite policy (§5) |
| memory budget | `memory_budget_bytes`: 80 % of free CUDA, half of MPS recommended working set, 4 GB CPU [V] | n/a | copy for tile/VAE-tile decisions |
| settings | `LibrarySettings` with `device`, `precision`, `memory_budget`; `LoadModelSettings` uses `shadow()` so a node overrides the library default [V] | per-node settings bags [V] | **copy** |
| model files | `MODEL_REF` inlet; catalog JSON per model under `catalog/` in OpenModelDB format; Models editor downloads; node never downloads in the worker [V] | same mechanism; "model not downloaded" status [V] | **copy**; add whole-repo entries |
| loaded-model type | `MODEL_BASE(PrimitiveType[SpandrelModel\|None])`, `store_strategy=StoreStrategy.NEVER`, `to_dict()` returns `{"value": {}}`, `from_dict()` returns `None`, custom `PrimitiveField` coercing non-model values to `None` [V] | result types only | **copy exactly** for all heavy wire types |
| runtime value | frozen dataclass `SpandrelModel(descriptor, device, dtype, name, notes, licence, lock)`, with a `threading.Lock` so two flows never drive one model [V] | n/a | **copy** (one lock per loaded component) |
| sharing / lifetime | `models_state().pool.acquire(key, self, load=, release=)`; `release_node` in `on_shutdown` and `on_teardown`; `on_shutdown` also does `self.out("loaded", None)` and `self.run_again()` [V] | cached estimator, released on change [V] | **copy**: this is the load-node lifecycle |
| cache key | `(resolved.key, (device, precision, flags))`; node remembers key in `self.cache.key`, releases when it changes [V] | n/a | **copy** |
| progress | `ProgressSettings` bag with `progress_field`; `with self.progress.busy("main", ...) as span: span.step(frac, text)` [V] | n/a | **copy** for sampler steps |
| cancel | `context.cancel` (`threading.Event`) polled between tiles; `Cancelled` caught, worker returns [V] | n/a | **copy** (per-step callback, §5) |
| warnings on card | `NodeWarning(n, source_version=None, kind=KIND)` via `wrapper.replace_warnings` [V] | n/a | **copy** for device/dtype/licence notes |
| non-commercial licence handling | setting gate plus `noncommercial.py` plus warning on the card [V] | n/a | **copy the idea** for non-OSI model licences (§4) |
| dynamic outlet kind | Load node's outlet starts as `ADD`, becomes the kind of the connected inlet (`_on_outlet_connected`, `rejig`) [V] | n/a | optional; probably **skip** (see §3.4) |
| tests | `tests/` with fake-model fixtures, `slow` marker for real weights [V] | same style | **copy**: no GPU in CI, fake pipelines |

Things spandrel does **not** give us: multi-component models, multi-GB downloads of folder repos
(haybale-models has it), step-wise cancellable loops (spandrel cancels per tile), and any handling of
sm_61.

---

## 2. Node catalog v1

ComfyUI-style names so users feel at home. Ports are `IN`/`OUT`, widgets are config. All sampling
nodes are `NodeType.DATA` workers like spandrel's. "Seed" is a plain INT inlet with a "control after
generate" config (`fixed`, `increment`, `randomize`) kept in node settings.

### 2.1 Loaders

| Node (ComfyUI analogue) | Inputs | Config | Outputs |
|---|---|---|---|
| **Load Checkpoint** (`CheckpointLoaderSimple`) | `ckpt` MODEL_REF (picker filtered to a `family` catalog field) | device, dtype (auto/fp16/bf16/fp32), offload (auto/none/model/sequential), vae tiling, shows licence + gated + VRAM estimate | `MODEL`, `CLIP`, `VAE` (see note) |
| **Load Diffusion Model** (`UNETLoader`) | `model` MODEL_REF | device, dtype, offload | `MODEL` |
| **Load CLIP** (`CLIPLoader`) | `clip` MODEL_REF | device, dtype, offload, `type` (sdxl, qwen3, ...) | `CLIP` |
| **Load VAE** (`VAELoader`) | `vae` MODEL_REF | device, dtype | `VAE` |

Note on diffusers: a diffusers repo is a folder of components, not one `.safetensors`. v1 Load Checkpoint
therefore takes a **whole-repo catalog entry** and returns three handles that share one folder snapshot
and load components lazily (`from_pretrained(folder, subfolder="unet")`, etc.). Single-file
`.safetensors` checkpoints (SDXL) can be supported through `from_single_file` as a later addition
**[I]**. The three-output split is what makes the graph ComfyUI-shaped, and it lets the VAE or text
encoder be swapped or shared (Z-Image and Flux.2 Klein both use Qwen3 encoders and Flux-family VAEs, but
different checkpoints, so sharing between families is not expected).

### 2.2 Conditioning

| Node | Inputs | Config | Outputs |
|---|---|---|---|
| **CLIP Text Encode** (`CLIPTextEncode`) | `clip` CLIP, `text` STRING (multiline), optional `text_2` for SDXL | prompt widget | `CONDITIONING` |
| **CLIP Set Last Layer** (`CLIPSetLastLayer`) | `clip` CLIP | `stop_at_clip_layer` INT | `CLIP` (SD1.x/SDXL only; later) |
| **Conditioning Zero Out** (`ConditioningZeroOut`) | `conditioning` | none | `CONDITIONING` (Turbo/Klein negative) |
| **Conditioning Combine / Concat / Average** | two `CONDITIONING` | strength for Average | `CONDITIONING` (later) |

SDXL needs two encoders plus pooled embeds plus size conditioning; the `CONDITIONING` value is a
family-tagged struct (§3.3) so one Text Encode node serves every family and the sampler unpacks it.

### 2.3 Latents

| Node | Inputs | Config | Outputs |
|---|---|---|---|
| **Empty Latent Image** (`EmptyLatentImage`, SD3 / Flux variants) | none | width, height (multiple of 16; family decides channels and 8x or 16x), batch_size | `LATENT` |
| **VAE Encode** (`VAEEncode`) | `image` IMAGE, `vae` VAE | none | `LATENT` |
| **Upscale Latent / By** | `LATENT` | method, size or factor | `LATENT` (later) |
| **Latent From Batch / Batch** | | | later |

### 2.4 Sampling

| Node | Inputs | Config | Outputs |
|---|---|---|---|
| **KSampler** (`KSampler`) | `model` MODEL, `positive` CONDITIONING, `negative` CONDITIONING, `latent_image` LATENT, `seed` INT | steps, cfg, sampler_name, scheduler, denoise | `LATENT` |
| **KSampler Advanced** (`KSamplerAdvanced`) | same | add_noise, noise_seed, start_at_step, end_at_step, return_with_leftover_noise | `LATENT` (v1.1) |

`sampler_name` and `scheduler` map onto diffusers schedulers (`FlowMatchEulerDiscreteScheduler`, and for
SDXL Euler, Euler a, DPM++ 2M, DPM++ 2M Karras, UniPC, DDIM) **[I]**. Not every ComfyUI name has a
diffusers twin; the list in the node is the set we can actually back. Families whose model card fixes the
sampler (Z-Image Turbo: guidance 0, 9 steps; Klein: guidance 1, 4 steps; Moss: 50 steps, cfg 3, shift 5,
layer skip) get a **family preset** applied when the user changes the model, shown as a card note, never
silently clamped.

### 2.4.1 Sampler design constraint

diffusers pipelines are monolithic `pipe(prompt=...)` calls. A granular KSampler must run the denoise
loop with explicit components: scheduler `set_timesteps`, transformer or UNet forward per step,
`scheduler.step`. Each family therefore needs a small adapter ("family driver") that knows how to build
latents, pack/unpack, and call its transformer. **This is the main engineering cost of the granular
design** and the reason v1 must be small (§4.4). Where a pipeline exposes the needed pieces
(`encode_prompt`, `prepare_latents`, `callback_on_step_end`) the driver reuses them **[I]**; exact
method names per family must be read from the diffusers source before implementing.

### 2.5 Decode and output

| Node | Inputs | Config | Outputs |
|---|---|---|---|
| **VAE Decode** (`VAEDecode`) | `samples` LATENT, `vae` VAE | tiled (auto/on/off), tile size | `IMAGE` (haybale-image `IMAGE`) |
| **VAE Decode (Tiled)** | same | tile_size, overlap | folded into the config above |
| **Save Image / Preview** | | | not needed: haybale-image already has display/save nodes |

Output uses `ImageValue.from_tensor(...)`, which exists in haybale-image (`value/image_value.py:138`)
**[V]** and keeps a torch tensor on its device with no copy, so a following spandrel upscale needs no
host round trip. Unverified: the tensor layout and range `from_tensor` expects. Read it before writing
VAE Decode.

### 2.6 Later (not v1)

Text to Image composite (macro `.hwm`, spandrel ships `macros/Upscaler.hwm` as precedent **[V]**), LoRA
loader, ControlNet, img2img (VAE Encode plus denoise<1 is already in v1 parts), inpaint, Qwen image edit.

---

## 3. Wire types and how big values flow

### 3.1 Verified mechanics

- `@type(wire_type=DataWire, store_strategy=StoreStrategy.NEVER, ...)` on a `PrimitiveType` subclass is
  how spandrel carries a loaded model **[V]** (`types/model.py`). `StoreStrategy.NEVER` means the port
  never saves its value; overriding `to_dict`/`from_dict` additionally guarantees nothing tensor-shaped is
  ever serialised **[V]**.
- A `PrimitiveType` cannot hold absence: the wire's default is `{"value": {}}` and a custom `PrimitiveField`
  coerces anything that is not the runtime class to `None`. We copy that **[V]**.
- Outlet values cross into other execution groups **as written**; a value on an outlet must never be
  mutated in place (node-canon, threading contract) **[V]**. Hence: all our runtime values are immutable
  (frozen dataclasses, tensors never modified after publish).
- A copied, pasted or loaded data node runs its worker once more (ADR 0070), so loaders must tolerate it
  and `on_shutdown` must null the outlet and call `run_again()` **[V]**.
- Node state that is not a port, setting or `self.store` is not saved; heavy objects belong in
  `on_startup`/worker and the pool, released in `on_shutdown` **[V]**.

### 3.2 Proposed types (all `StoreStrategy.NEVER`, colour per family of wire)

| Type | Runtime value | Contents |
|---|---|---|
| `MODEL` | `DiffusionModel` frozen dataclass | handle to loaded denoiser (transformer or UNet), family id, scheduler config, device, dtype, `lock`, notes, licence |
| `CLIP` | `TextEncoderModel` | tokenizer(s), encoder(s), family id, device, dtype, `lock` |
| `VAE` | `VaeModel` | autoencoder, scale/shift factors, spatial and channel factor, tiling flag, `lock` |
| `CONDITIONING` | `Conditioning` | family id, list of tensors (prompt embeds, pooled embeds, masks, SDXL size ids); **CPU or model device, recorded** |
| `LATENT` | `LatentValue` | tensor `[B,C,H,W]`, family id, channel count, scale factor, optional noise mask |

Naming: ComfyUI users know `MODEL`, `CLIP`, `VAE`, `CONDITIONING`, `LATENT`. spandrel already defines a
type labelled "Loaded model"/`MODEL_BASE`; registry keys are library-prefixed
(`haybale-diffusion:type:MODEL`) so there is no clash **[V]** (keys are `<library>:type:<id>`), but
labels in the UI should say "Diffusion model", "Text encoder (CLIP)", "VAE" to avoid confusion with
spandrel's.

A shared base `LOADED_BASE` per spandrel's `MODEL_BASE` can carry `to_dict`/`from_dict`/field coercion
once; the five types derive from it (or from a sibling for the two tensor types).

### 3.3 Ownership and lifetime

- **Loaded components** (`MODEL`, `CLIP`, `VAE`): owned by the pool (`LoadedModels`, refcounted by
  holder = loader node). The wire value is a *reference*; downstream nodes never release. The pool frees
  when the last loader releases (`on_shutdown`). **[V]** for the pool and lifecycle; **[I]** that
  holding a reference on the wire beyond `on_shutdown` is harmless, which is why spandrel nulls the
  outlet there.
- **Tensors** (`CONDITIONING`, `LATENT`): owned by whoever holds the value; plain GC. Immutable once
  emitted. Keep conditioning tensors on CPU by default (small, and lets the encoder be offloaded before
  the denoiser loads); the sampler moves them. Latents stay on the producing device (they are small:
  1024x1024 is 4 to 32 channels at 1/8 to 1/16 size).
- **Concurrency**: one `threading.Lock` per loaded component, like `SpandrelModel.lock`. A second graph
  running the same checkpoint serialises on it **[V]** pattern.
- **Wire value in saved graphs**: nothing. Loader nodes save their MODEL_REF, settings and node-local
  config; wire values are recomputed on first run (ADR 0070 **[V]**).

### 3.4 Dynamic outlet kind: do not copy it

spandrel's Load node morphs its outlet type to fit the connected node. We have three fixed loaders and
fixed output types, which is closer to ComfyUI and simpler. Skip `_on_outlet_connected` machinery.

### 3.5 Unverified, check before node code

- Whether a `DataWire` value can carry a bare `torch.Tensor` without framework copies or `deepcopy`
  somewhere in the edge path (BUNDLE/`CarrierValue` exists; `ImageValue` already carries tensors, which
  suggests yes) **[I]**.
- How `LatentValue` should expose a preview (a viewer widget that decodes cheaply) **[I]**.

---

## 4. Model families for v1

All repo ids and licences below were read from the Hub model card or `model_index.json` this session
**[V]** unless marked. Gated status: "no gating notice on the page" is **not** proof of open access; see
open question 5. VRAM figures are the model cards' where given, otherwise **my arithmetic from parameter
counts [I]**.

| Family | HF repo | Licence (card) | Components (diffusers) | Params | Card VRAM / my estimate |
|---|---|---|---|---|---|
| **SDXL base 1.0** | `stabilityai/stable-diffusion-xl-base-1.0` | CreativeML Open RAIL++-M [V] | `unet` UNet2DConditionModel, `text_encoder` (CLIP-L), `text_encoder_2` (OpenCLIP-G), `vae`, `scheduler`; fp16 variant files exist (unet fp16 5.14 GB vs 10.3 GB) [V] | UNet ~2.6B, 3B total per card | no card figure; [I] ~7 GB fp16 weights, fits 11 GB with VAE tiling |
| **Z-Image Turbo** | `Tongyi-MAI/Z-Image-Turbo` | Apache-2.0 [V] | `transformer` (S3-DiT), `text_encoder` Qwen3 (transformers), `tokenizer`, `vae` AutoencoderKL, `scheduler` FlowMatchEuler; `ZImagePipeline` [V] | 6B (DiT) | card: "fits comfortably within 16G"; 9 steps, guidance 0 [V]. [I] DiT ~12 GB in bf16/fp16 plus encoder, needs offload on 11 GB |
| **FLUX.2 Klein 4B** | `black-forest-labs/FLUX.2-klein-4B` | Apache-2.0 [V] | `transformer` Flux2Transformer2DModel, `text_encoder` Qwen3ForCausalLM, `tokenizer`, `vae` AutoencoderKLFlux2, `scheduler`; `Flux2KleinPipeline`, distilled, 4 steps, guidance 1 [V] | 4B | card ~13 GB at 1024²; offload suggested [V] |
| **Moss Image (SFT, Base)** | `OpenMOSS-Team/MOSS-Image-SFT` (and `-Base`) | Apache-2.0 [V] | `transformer` MOSSImageTransformer and `scheduler` MOSSImageScheduler (custom classes), `text_encoder` Qwen3_5Model, `vae` AutoencoderKLFlux2; **needs `custom_pipeline="pipeline_moss_image"` and `trust_remote_code=True`**; diffusers >=0.38, transformers >=5.3, torch >=2.9; 50 steps, cfg 3, shift 5, negative layer skip 22 [V] | 5B DiT; encoder size third-party-reported as 9B (not verified) | no card figure; [I] encoder alone about 18 GB bf16, so 1080 Ti needs offload or quantisation |

Whether each of these runs on our hardware (the part the owner cares about most):

| Family | 1080 Ti (fp16, no bf16 cores) | Apple MPS |
|---|---|---|
| SDXL | **Yes, the safe baseline.** Ships an fp16 variant; the fp16 VAE overflow issue (black or NaN images) is well known, so decode in fp32 or use a fp16-safe VAE **[I]**. Fits 11 GB. | Yes, fp16 works in diffusers on MPS; unified memory limits at about 16 GB machines **[I]** |
| Z-Image Turbo | **Unknown.** Cards recommend bf16; fp16 correctness of Qwen3 and the DiT is untested here. Pascal executes bf16 only via slow emulation or upcast **[I]**. 12 GB DiT does not fit 11 GB without offload. | **Unknown**; MPS bf16 support depends on macOS version **[I]** |
| Flux.2 Klein 4B | **Unknown** (same bf16 weights concern). ~13 GB needs offload on 11 GB, which is slow but feasible **[I]**. | **Unknown** |
| Moss Image | **Likely not usable in v1**: custom remote code, 5B DiT plus a large Qwen3.5 encoder, bf16 + fp32 VAE recipe, 50 steps. Needs quantisation or sequential offload. | **Unknown**, remote code pins new transformers/torch |

**Cannot be settled by reading.** Everything marked Unknown needs a 15-minute smoke test on the real
1080 Ti and a Mac: load each family in fp16 and bf16, 512x512 and 1024x1024, 2 steps, compare images and
peak VRAM. That test belongs at the start of step 1 (§7), not after the node set is built.

### 4.4 Recommended minimal first set

1. **SDXL base 1.0.** Only family that is documented fp16, ships an fp16 variant, fits 11 GB, and is the
   archetype of the ComfyUI workflow (two encoders, UNet, KSampler). Forces the whole granular graph to be
   real. Licence is OpenRAIL++-M (use restrictions, not OSI): show it in the Load node, **a decision for the
   owner** (question 3).
2. **Z-Image Turbo**, behind the smoke test. Apache-2.0, 8 steps, guidance 0 makes a fast demo and
   exercises the flow-matching DiT path plus Qwen3 encoder. Ship only if fp16 (or offloaded bf16) gives
   correct images on the 1080 Ti; otherwise mark it "CUDA >= Turing / Apple" and still ship.
3. **Flux.2 Klein 4B** second wave (same driver family as 2, Qwen3 encoder, FLUX.2 VAE).
4. **Moss Image: defer.** Remote code (`trust_remote_code=True`) is a security prompt we should not
   auto-accept in a library that downloads and runs code; heavy; bleeding-edge pins. Revisit when diffusers
   ships it natively.

---

## 5. Runtime concerns

### 5.1 Device, dtype, VRAM: what a ComfyUI-class manager does, adapted **[I]**

Not re-read from source; this is behaviour from general knowledge, restated as requirements for us.

- Picks one torch device per model (cuda index, mps, cpu), with a "main" device and optionally a separate
  one for text encoder and VAE. We map that onto per-node `device` settings (spandrel's `shadow`).
- Chooses dtype per model from device capabilities (fp16 on pre-Ampere NVIDIA, bf16 where fast, fp32
  fallback; VAE often forced fp32 or bf16). We put this in `resolve_dtype`, extended with: **fp16
  correctness table per family** (a catalog field), bf16 only if `torch.cuda.is_bf16_supported()` and
  compute capability >= 8.0, never silently emulate.
- Tracks free VRAM and moves models between GPU and CPU on demand (partial offload, "lowvram"/"novram"
  tiers). We use diffusers' own offload (`enable_model_cpu_offload`, `enable_sequential_cpu_offload`,
  VAE tiling/slicing) per component, selected by the Load node's `offload` setting. `auto` = estimate
  weights vs `memory_budget_bytes` and choose none/model/sequential. Unverified that component-level
  offload works with our split (MODEL/CLIP/VAE as separate handles); the hooks are accelerate-based and
  attach to modules, so it should **[I]**.
- Attention backend: use torch SDPA (`torch.nn.functional.scaled_dot_product_attention`), diffusers'
  default. xformers/flash-attn are out for v1 (Pascal can't run FlashAttention 2; MPS has none).
- MPS quirks to plan for **[I]**: set `PYTORCH_ENABLE_MPS_FALLBACK=1` for unsupported ops (process-wide,
  set once at import of the runtime module, documented), avoid float64, fp16 VAE issues, `torch.mps.empty_cache()`
  on release (spandrel's `release_model` already does this **[V]**), Generator on `cpu` for reproducible seeds
  (Moss' card does this too **[V]**), unified memory means "VRAM" = system RAM so the budget logic in
  `memory_budget_bytes` (half of recommended working set) is the right start **[V]**.

### 5.2 Device selection needs an arch check (new, from §0)

`resolve_device("auto")` must not trust `torch.cuda.is_available()`. Add: for each CUDA device compare
`torch.cuda.get_device_capability(i)` with `torch.cuda.get_arch_list()`; if the card's `sm_XY` is not in the list
(and no PTX `compute_*` entry covers it) mark that device **unusable** and say so on the card:
"GTX 1080 Ti (sm_61) is not supported by torch 2.15+cu132; install the `cuda-legacy` extra". Falls back
to the next device or cpu with the same note-on-fallback pattern spandrel uses **[V]** pattern.

### 5.3 Non-blocking execution, progress, cancellation

- Workers run in the execution group's thread, not the UI loop **[V]** (spandrel's long upscale does the
  same). The sampler loop is long but each step is short; update progress per step with
  `ProgressSettings`/`span.step` **[V]** (throttled to 50 ms by the framework).
- Cancellation: `context.cancel` is documented as set when "a stop that timed out kills the run" **[V]**.
  So graceful stop is mostly cooperative via the framework's stop, and `cancel` is the hard path. The
  sampler checks `context.cancel` every step (cheap) and returns without emitting, like `Cancelled` in
  spandrel. A single step cannot be interrupted; at 1024² on a 1080 Ti an SDXL step is a few seconds
  **[I]**, which is the worst-case stop latency.
- Downloads never happen in a worker: the Models editor/needs-list downloads (queue, resume, progress
  already exist **[V]**), the worker raises "model missing, fetch it" via `resolve_port` and the
  `ModelMissing` warning **[V]**. Multi-GB repo downloads therefore reuse haybale-models UX.

### 5.4 Model cache between runs

`LoadedModels` frees at the last `release`, i.e. at `on_shutdown` when the graph stops **[V]**. For
diffusion this is painful (SDXL load is tens of seconds). Options: (a) accept it (spandrel behaviour),
(b) keep-alive: delay release by N minutes via a library setting, implemented in our `release` callback
or a library state, without changing haybale-models. Recommend (a) for step 1, (b) as a follow-up,
**owner decision** (question 6). Pool key = `(resolved.key, (device, dtype, offload, component))` **[V]** pattern.

### 5.5 Two GPUs

The dev machine has two 1080 Ti (confirmed with `nvidia-smi`, 11264 MiB each **[V]**). Cheap v1 use:
each loader node has a `device` setting, so users place text encoder on `cuda:1` and the denoiser on
`cuda:0`; conditioning is CPU-resident so crossing devices costs nothing **[design]**. No tensor
parallelism, no multi-GPU single model in v1. Two graphs sampling concurrently on separate GPUs is
possible because locks are per component **[I]**. Device ids in settings are strings, spandrel already
accepts `cuda:N` **[V]**.

### 5.6 Gated models, HF token, licence display

- haybale-models downloads through `huggingface_hub` into the HF cache with explicit `cache_dir`, and
  never sets env vars **[V]** (`hf.py` docstring). How it passes a token, and how a gated-repo 401/403
  surfaces in the Models editor, was **not read**. Verify before relying on it **[open]**.
- None of the four families' cards displayed a gating notice in what I fetched, but the fetch tool cannot
  prove that. Treat as unverified.
- Licence on the card: catalog JSON already has `license` and `commercial` fields, and the Models editor
  shows them **[V]** (`model-catalogs.md` §2.3). The Load node additionally shows licence text and
  a link on its card and as a `NodeWarning` for non-OSI licences (OpenRAIL++-M), the spandrel
  `noncommercial` pattern **[V]**. Keep `commercial: true` only where the licence says so; do not infer.

---

## 6. Packaging

**Current state of this repo [V]:** scaffold only; `barn/haybale-diffusion/pyproject.toml` from
`haywire init`, no dependencies yet. Root `pyproject.toml` uses `haywire-studio>=0.3.4` etc. from
PyPI, with a uv workspace over `barn/*`.

**What `uv sync` does today in spandrel [V]:** plain `torch` dependency resolves to PyPI `torch 2.15.0`
which on Linux x86_64 is `+cu132` and pulls about 43 `nvidia-*` packages (spandrel's `uv.lock` has 43
`name = "nvidia-` entries; multi-GB). On macOS PyPI's torch is the CPU/MPS wheel. This is fine for
spandrel and wrong for our 1080 Ti (§0).

### 6.1 Extras layout (proposal)

```toml
[project]
dependencies = [
  "haywire-core>=0.3.4", "haybale-core>=0.3.4", "haybale-image>=0.3.4", "haybale-models>=0.3.4",
  "diffusers>=0.42", "transformers>=5.3", "accelerate>=1.10", "safetensors>=0.6",
  "numpy",
]
[project.optional-dependencies]
cuda    = ["torch>=2.9"]                 # PyPI default: cu13, Turing and newer
cuda-legacy = ["torch>=2.9,<2.15"]       # Pascal/Maxwell/Volta: needs the cu126 index (below)
mps     = ["torch>=2.9"]                 # macOS wheels from PyPI
cpu     = ["torch>=2.9"]
```

Extras that differ only by index cannot be expressed by metadata alone; the *index* is a property of the
installing project, not the library. So:

- **Library wheel**: depends on `torch` unpinned-ish (`>=2.9`) with **no index**, plus the extras above as
  documentation of intent. The library must import and show its nodes without torch (lazy import **[V]**
  pattern), and show a clear "torch not installed / not CUDA-capable here" status in the Load node.
- **This dev workspace** (root `pyproject.toml`, uv only): pin torch per platform with uv sources:

```toml
[tool.uv.sources]
torch = [
  { index = "pytorch-cu126", marker = "sys_platform == 'linux'" },
]
[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true
[tool.uv]
constraint-dependencies = ["torch>=2.9,<2.15; sys_platform == 'linux'"]
```

  macOS gets PyPI torch (MPS) because the marker excludes it. Pattern from uv docs **[I]**; the cu126
  2.14.1 wheel exists **[V]**, but this exact `pyproject` was **not run**. First thing to try in step 1.
- Users installing the published library from a marketstall get whatever torch pip picks (cu13 on Linux).
  A Pascal user must follow a documented recipe (`uv pip install "torch<2.15" --index-url
  https://download.pytorch.org/whl/cu126`). The device check (§5.2) is the safety net that explains it.
  **Constraint**: `haywire share` must remain usable; do not hand-edit generated fields (CLAUDE.md).

### 6.2 Install size warning

torch on Linux CUDA wheels is on the order of several GB with the nvidia libraries (observed: 43 nvidia
packages in spandrel's lock **[V]**), plus the model downloads: SDXL repo is 76.9 GB in total on the Hub
(all formats, `include` patterns are needed) **[V]**, with the fp16 UNet at 5.14 GB **[V]**. So catalog
entries must use `include` globs to pull only `*.json`, tokenizer files and the `*.fp16.safetensors`
files (supported by the whole-repo `include` field **[V]**). Put the install size in README and in the
Load node's "needs" line.

---

## 7. Recommended order of small PRs

Each is independently reviewable, local branch until the owner says otherwise. None touches versions or
releases (CLAUDE.md).

0. **Environment smoke test (no library code).** In a scratch venv: torch 2.14.1+cu126 on the 1080 Ti,
   load SDXL fp16 and Z-Image / Klein in fp16 and bf16, record images, peak VRAM, speed; same on a Mac
   if one is available. Output: a table that replaces every "Unknown" in §4. Needs the owner's Mac.
1. **Packaging and workspace pins** (§6): root `pyproject` uv sources/index for cu126 on Linux,
   library dependencies and extras, `uv sync --frozen` check on Linux. Also check
   `from haybale_diffusion import Library` imports without torch.
2. **Runtime core, no nodes**: `runtime/devices.py` (copy + arch check), settings class
   (`device`, `precision`, `offload`, `memory_budget`), `runtime/cache.py` pool wrapper, tests with fakes.
3. **Types** (`MODEL`, `CLIP`, `VAE`, `CONDITIONING`, `LATENT`) with NEVER/`from_dict -> None` and unit tests
   that a saved graph holds no tensors.
4. **Catalog + SDXL loaders**: `catalog/sdxl-base-1.0.json` with `include` globs and licence,
   Load Checkpoint, tests with a tiny fake diffusers folder.
5. **CLIP Text Encode, Empty Latent, VAE Decode** for SDXL (decode to `ImageValue`).
6. **KSampler (SDXL driver)** with progress and cancel, then a manual end-to-end graph, then the macro
   "Text to Image" last.
7. Z-Image Turbo driver (and Load Diffusion Model / Load CLIP / Load VAE if the component split needs it).
8. Flux.2 Klein driver.
9. KSampler Advanced, VAE Encode, img2img.
10. Keep-alive cache setting, two-GPU docs.

---

## 8. Open questions for the owner

1. **Pascal policy.** OK to make "dev workspace pins torch<2.15 / cu126 on Linux" the plan, knowing a
   plain `pip install haybale-diffusion` on Linux gives a torch that cannot run a 1080 Ti? Or do we
   ship a documented `cuda-legacy` recipe only?
2. **Which families are v1-blocking?** Proposal: SDXL required; Z-Image and Klein required only if the
   step-0 smoke test passes on the 1080 Ti.
3. **OpenRAIL++-M for SDXL** carries use restrictions and is not OSI. Acceptable as a v1 default
   with the licence shown in the Load node? (Apache-2.0 families need no gate.)
4. **Moss Image**: agree to defer because of `trust_remote_code`?
5. **HF token / gated repos**: is there a haybale-models setting for the token? I did not verify how it
   handles 401/403; if there is none, should this library ask haybale-models for one rather than
   implement its own?
6. **Model keep-alive** between graph runs: accept free-on-stop (spandrel behaviour) for v1?
7. **Single-file checkpoints** (`from_single_file`, CivitAI-style `.safetensors`): needed in v1 for
   ComfyUI-folder users, or whole-repo only?
8. **Mac test machine**: available for step 0, and which macOS and RAM?
9. **Library licence**: MIT like spandrel/visiongraph (pyproject says MIT there)? This repo's own
   `barn/.../pyproject.toml` has not been decided by me.
10. **Remote-code policy** as a general rule (never `trust_remote_code=True` from a node)?

## Sources

- Local, read: `../haybale-spandrel/{CLAUDE.md,pyproject.toml,barn/**/runtime/*.py,nodes/*.py,types/model.py,value/spandrel_model.py,settings/*.py,catalog/README.md}`,
  `../haybale-visiongraph/{pyproject.toml,barn/**/nodes/base_estimator_node.py}`,
  `../haywire-repo/docs/{haybale/haybale-canon.md,guides/model-catalogs.md,components/datatypes/datatype-canon.md,components/nodes/node-canon.md}`,
  `../haywire-repo/barn/haybale-models/haybale_models/{pool.py,consumer.py,hf.py,sources/hf.py,value/model_ref.py}`,
  `../haywire-repo/packages/haywire-core/src/haywire/{core/types/enums.py,core/execution/execution_context.py,barn/builtin/progress.py}`.
- Local, run: `nvidia-smi`; `../haybale-spandrel/.venv/bin/python -I` torch arch list; `uv pip compile` of the diffusers stack.
- Web: HF model cards and `model_index.json` for `stabilityai/stable-diffusion-xl-base-1.0` (+ `unet/`
  and tree listing), `Tongyi-MAI/Z-Image-Turbo`, `black-forest-labs/FLUX.2-klein-4B`,
  `OpenMOSS-Team/MOSS-Image-SFT`; PyTorch dev-discuss notice "CUDA 12.6 wheels will no longer be published
  from PyTorch 2.15 (drops Maxwell / Pascal / Volta)"; the `download.pytorch.org/whl/cu126/torch/` index.
- Not read: ComfyUI source (by design), the Hugging Face "Moss Image" third-party blogs (used only to
  learn the repo name; the 9B encoder size is from them and unverified), diffusers family driver internals.

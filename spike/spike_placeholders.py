"""Spike part 2: workflow exchange + placeholder rewrite with comfyui-tooling-nodes (Option A).

Publishes a placeholder workflow ourselves (standing in for ComfyUI's browser), receives it as a
subscriber, rewrites the placeholders, runs it twice, logs every message.
"""
import asyncio, base64, json, struct, sys, time, uuid
import httpx, websockets

BASE = "127.0.0.1:8189"
OUT, INPUT_PNG = sys.argv[1], sys.argv[2]

PLACEHOLDER_WF = {
    "10": {"class_type": "ETN_Parameter", "inputs": {"name": "Prompt", "type": "prompt (positive)", "default": "a green pear"}},
    "11": {"class_type": "ETN_Parameter", "inputs": {"name": "Strength", "type": "number", "default": "0.6", "min": 0.0, "max": 1.0}},
    "12": {"class_type": "ETN_Parameter", "inputs": {"name": "Seed", "type": "number (integer)", "default": "1", "min": 0, "max": 2**31}},
    "20": {"class_type": "ETN_KritaImageLayer", "inputs": {"name": "Source"}},
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["10", 0], "clip": ["1", 1]}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
    "4": {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["1", 2]}},
    "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
          "latent_image": ["4", 0], "seed": ["12", 0], "steps": 6, "cfg": 7.0, "sampler_name": "euler",
          "scheduler": "normal", "denoise": ["11", 0]}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "30": {"class_type": "ETN_KritaOutput", "inputs": {"images": ["6", 0], "x": 0, "y": 0, "name": "Result",
           "batch_mode": "default", "resize_canvas": False}},
}

def rewrite(wf, values, images):
    """Placeholder -> literal (Parameter) or base64 loader (image layer); other nodes copied."""
    literal = {nid: values[n["inputs"]["name"]] for nid, n in wf.items() if n["class_type"] == "ETN_Parameter"}
    out = {}
    for nid, n in wf.items():
        if nid in literal:
            continue
        if n["class_type"] == "ETN_KritaImageLayer":
            out[nid] = {"class_type": "ETN_LoadImageBase64", "inputs": {"image": images[n["inputs"]["name"]]}}
            continue
        inputs = {k: (literal[v[0]] if isinstance(v, list) and v and v[0] in literal else v) for k, v in n["inputs"].items()}
        out[nid] = {"class_type": n["class_type"], "inputs": inputs}
    return out

async def collect(ws, pid, tag, log):
    t0 = time.time()
    while True:
        m = await asyncio.wait_for(ws.recv(), timeout=300); t = round(time.time() - t0, 3)
        if isinstance(m, bytes):
            a, b = struct.unpack(">II", m[:8]); fn = f"{OUT}/{tag}_{len(log)}.png"; open(fn, "wb").write(m[8:])
            log.append({"t": t, "run": tag, "kind": "binary", "header": [a, b], "len": len(m), "magic": m[8:12].hex()})
            continue
        j = json.loads(m)
        if j["type"] != "progress_state":
            log.append({"t": t, "run": tag, "kind": "json", "msg": j})
        if j["type"] in ("execution_success", "execution_error", "execution_interrupted") and j["data"].get("prompt_id") == pid:
            return

async def main():
    sub_id, log = str(uuid.uuid4()), []
    http = httpx.Client(base_url=f"http://{BASE}", timeout=30)
    async with websockets.connect(f"ws://{BASE}/ws?clientId={sub_id}", max_size=None) as ws:
        await ws.recv()
        r = http.post("/api/etn/workflow/subscribe", json={"client_id": sub_id})
        log.append({"kind": "subscribe", "status": r.status_code, "body": r.text})
        # stand-in publisher with its own client id
        r = http.post("/api/etn/workflow/publish", json={"name": "spike-img2img", "client_id": "spike-publisher", "workflow": PLACEHOLDER_WF})
        log.append({"kind": "publish", "status": r.status_code, "body": r.text})
        received = None
        while received is None:
            m = await asyncio.wait_for(ws.recv(), timeout=10)
            if isinstance(m, str):
                j = json.loads(m); log.append({"kind": "json", "run": "exchange", "msg": j})
                if j["type"] == "etn_workflow_published":
                    received = j["data"]["workflow"]
        log.append({"kind": "roundtrip_equal", "value": received == PLACEHOLDER_WF})
        # placeholders run unrewritten (dummy values)?
        r = http.post("/prompt", json={"prompt": PLACEHOLDER_WF, "client_id": sub_id})
        log.append({"kind": "post_unrewritten", "status": r.status_code, "body": r.json()})
        if r.status_code == 200:
            await collect(ws, r.json()["prompt_id"], "unrewritten", log)
        img = base64.b64encode(open(INPUT_PNG, "rb").read()).decode()
        wf = rewrite(received, {"Prompt": "a green pear on a table", "Strength": 0.6, "Seed": 5}, {"Source": img})
        json.dump({k: v for k, v in wf.items() if k != "20"}, open(f"{OUT}/rewritten_wf_without_image.json", "w"), indent=1)
        for tag in ("rewritten1", "rewritten2_identical"):
            r = http.post("/prompt", json={"prompt": wf, "client_id": sub_id})
            log.append({"kind": "post", "run": tag, "status": r.status_code, "body": r.json()})
            if r.status_code == 200:
                await collect(ws, r.json()["prompt_id"], tag, log)
        r = http.post("/api/etn/workflow/unsubscribe", json={"client_id": sub_id})
        log.append({"kind": "unsubscribe", "status": r.status_code, "body": r.text})
    json.dump(log, open(f"{OUT}/placeholder_log.json", "w"), indent=1)

asyncio.run(main())

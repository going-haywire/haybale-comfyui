"""Spike: submit a tiny SD1.5 workflow, log every websocket message; run it twice to see caching."""
import asyncio, json, struct, sys, time, uuid
import httpx, websockets

BASE = "127.0.0.1:8189"
OUT = sys.argv[1]

def workflow(seed):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red apple on a table", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
              "latent_image": ["4", 0], "seed": seed, "steps": 6, "cfg": 7.0, "sampler_name": "euler",
              "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImageWebsocket", "inputs": {"images": ["6", 0]}},
    }

async def run(ws, client_id, wf, tag, log):
    r = httpx.post(f"http://{BASE}/prompt", json={"prompt": wf, "client_id": client_id}, timeout=30)
    resp = r.json(); pid = resp.get("prompt_id")
    log.append({"t": 0, "run": tag, "kind": "post_prompt_response", "status": r.status_code, "body": resp})
    t0 = time.time()
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout=300)
        t = round(time.time() - t0, 3)
        if isinstance(msg, bytes):
            a, b = struct.unpack(">II", msg[:8])
            fn = f"{OUT}/{tag}_frame_{len(log)}.png"
            open(fn, "wb").write(msg[8:])
            log.append({"t": t, "run": tag, "kind": "binary", "header": [a, b], "len": len(msg), "png_magic": msg[8:12].hex(), "file": fn})
        else:
            m = json.loads(msg); log.append({"t": t, "run": tag, "kind": "json", "msg": m})
            if m["type"] in ("execution_success", "execution_error", "execution_interrupted") and m["data"].get("prompt_id") == pid:
                break
            if m["type"] == "executing" and m["data"].get("node") is None and m["data"].get("prompt_id") == pid:
                break
    return pid

async def main():
    client_id = str(uuid.uuid4()); log = []
    async with websockets.connect(f"ws://{BASE}/ws?clientId={client_id}", max_size=None) as ws:
        first = json.loads(await ws.recv()); log.append({"t": 0, "run": "connect", "kind": "json", "msg": first})
        pid1 = await run(ws, client_id, workflow(42), "run1", log)
        pid2 = await run(ws, client_id, workflow(42), "run2_identical", log)
        # drain anything trailing briefly
        try:
            while True:
                m = await asyncio.wait_for(ws.recv(), timeout=2)
                log.append({"t": -1, "run": "trailing", "kind": "binary" if isinstance(m, bytes) else "json",
                            "msg": None if isinstance(m, bytes) else json.loads(m)})
        except asyncio.TimeoutError:
            pass
    hist = httpx.get(f"http://{BASE}/history/{pid1}", timeout=30).json()
    json.dump(log, open(f"{OUT}/ws_log.json", "w"), indent=1)
    json.dump(hist, open(f"{OUT}/history_run1.json", "w"), indent=1)
    print("done", pid1, pid2, len(log), "messages")

if __name__ == "__main__":
    asyncio.run(main())

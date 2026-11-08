import asyncio, json, sys, uuid, httpx, websockets
sys.path.insert(0, "."); from spike_core import workflow, BASE
OUT = sys.argv[1]
async def main():
    out = {}
    bad = workflow(1); bad["1"]["inputs"]["ckpt_name"] = "missing.safetensors"
    r = httpx.post(f"http://{BASE}/prompt", json={"prompt": bad, "client_id": "x"}); out["bad_ckpt"] = {"status": r.status_code, "body": r.json()}
    cid = str(uuid.uuid4()); msgs = []
    async with websockets.connect(f"ws://{BASE}/ws?clientId={cid}", max_size=None) as ws:
        await ws.recv()
        pid = httpx.post(f"http://{BASE}/prompt", json={"prompt": workflow(7777), "client_id": cid}).json()["prompt_id"]
        while True:
            m = await ws.recv()
            if isinstance(m, bytes): msgs.append("BINARY"); continue
            m = json.loads(m); msgs.append(m)
            if m["type"] == "progress" and m["data"]["node"] == "5" and m["data"]["value"] >= 2:
                ir = httpx.post(f"http://{BASE}/interrupt", json={"prompt_id": pid}); msgs.append({"interrupt_status": ir.status_code, "body": ir.text})
            if m["type"] in ("execution_success", "execution_error", "execution_interrupted"): break
    out["interrupt"] = [x for x in msgs if not (isinstance(x, dict) and x.get("type") == "progress_state")]
    json.dump(out, open(f"{OUT}/errors.json", "w"), indent=1)
asyncio.run(main())

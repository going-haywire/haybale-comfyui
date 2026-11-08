"""Subscribe and log every etn_workflow_published message for a while (browser-side publish)."""
import asyncio, json, sys, time, uuid, httpx, websockets
BASE, OUT, SECS = "127.0.0.1:8189", sys.argv[1], int(sys.argv[2])
async def main():
    cid, got = str(uuid.uuid4()), []
    async with websockets.connect(f"ws://{BASE}/ws?clientId={cid}", max_size=None) as ws:
        await ws.recv()
        print("subscribe", httpx.post(f"http://{BASE}/api/etn/workflow/subscribe", json={"client_id": cid}).status_code, flush=True)
        end = time.time() + SECS
        while time.time() < end:
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
            except asyncio.TimeoutError:
                break
            if isinstance(m, str) and json.loads(m)["type"] == "etn_workflow_published":
                got.append(json.loads(m)); json.dump(got, open(OUT, "w"), indent=1)
                print("published", len(got), got[-1]["data"]["publisher"], flush=True)
        httpx.post(f"http://{BASE}/api/etn/workflow/unsubscribe", json={"client_id": cid})
    print("done", len(got))
asyncio.run(main())

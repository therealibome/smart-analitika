from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from analyzer import SmartDataAnalyzer
from exporter import HDExporter
import uvicorn
import asyncio
import httpx
import json
import base64
import random
import string
import os
from datetime import datetime

app = FastAPI(title="Smart Analytics Engine Pro")

BOT_TOKEN = "8936728709:AAFeq1IgWiLG7Gh9Cs1DsYfwE-oRgxaSHkI"  # @BotFather tokeningiz
ADMIN_ID = "6758258778"  # @userinfobot ID ingiz

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

CURRENT_DATA = {}
active_websockets = []
last_update_id = 0
admin_status = "online"
missed_messages = []

users_db = {}
uploaded_files_history = []
current_admin_otp = None


class UserAuth(BaseModel):
    username: str
    password: str


class AdminOTPVerify(BaseModel):
    otp: str


class ResetPasswordModel(BaseModel):
    username: str
    new_password: str


# ==========================================
# 🔐 AUTHENTICATION
# ==========================================
@app.post("/api/register")
async def register_user(user: UserAuth):
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="Ushbu username mavjud!")

    if len(user.password) < 8:
        raise HTTPException(status_code=400, detail="Parol kamida 8 ta belgidan iborat bo'lishi shart!")

    users_db[user.username] = {
        "password": user.password,
        "registered_at": datetime.now().strftime('%Y-%m-%d %H:%M')
    }

    if BOT_TOKEN != "SIZNING_BOT_TOKENINGIZ":
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_ID,
                        "text": f"🎉 Yangi user ro'yxatdan o'tdi!\n\n👤 Username: @{user.username}\n📅 Vaqt: {users_db[user.username]['registered_at']}"
                    }
                )
            except Exception as e:
                print("Telegram Error:", e)

    return {"status": "success", "username": user.username}


@app.post("/api/login")
async def login_user(user: UserAuth):
    if user.username not in users_db or users_db[user.username]["password"] != user.password:
        raise HTTPException(status_code=400, detail="Username yoki parol xato!")
    return {"status": "success", "username": user.username}


# ==========================================
# 👑 ADMIN PANEL API
# ==========================================
@app.post("/api/admin/request-otp")
async def request_admin_otp():
    global current_admin_otp
    otp = ''.join(random.choices(string.digits, k=6))
    current_admin_otp = otp

    if BOT_TOKEN != "SIZNING_BOT_TOKENINGIZ":
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_ID,
                        "text": f"🔑 ADMIN PANELGA KIRISH KODI:\n\n👉 `{otp}` 👈",
                        "parse_mode": "Markdown"
                    }
                )
            except Exception:
                raise HTTPException(status_code=500, detail="Telegram bot bilan aloqa yo'q")

    return {"status": "success", "message": "OTP Yuborildi"}


@app.post("/api/admin/verify-otp")
async def verify_admin_otp(data: AdminOTPVerify):
    global current_admin_otp
    if not current_admin_otp or data.otp != current_admin_otp:
        raise HTTPException(status_code=400, detail="Xato yoki eskirgan kod!")
    current_admin_otp = None
    return {"status": "success"}


@app.get("/api/admin/data")
async def get_admin_data():
    return {
        "status": "success",
        "users": [{"username": k, "registered_at": v["registered_at"]} for k, v in users_db.items()],
        "files": uploaded_files_history
    }


@app.delete("/api/admin/delete-user/{username}")
async def delete_user(username: str):
    global CURRENT_DATA, uploaded_files_history
    if username in users_db:
        del users_db[username]

        # Userga tegishli barcha yuklangan fayllarni va joriy analitika xotirasini tozalash
        uploaded_files_history = [f for f in uploaded_files_history if f.get("username") != username]
        if CURRENT_DATA.get("uploaded_by") == username:
            CURRENT_DATA = {}

        return {"status": "success", "message": f"@{username} to'liq o'chirildi va ma'lumotlari tozalandi"}
    raise HTTPException(status_code=404, detail="User topilmadi")


@app.post("/api/admin/reset-password")
async def reset_password(data: ResetPasswordModel):
    if data.username in users_db:
        if len(data.new_password) < 8:
            raise HTTPException(status_code=400, detail="Yangi parol kamida 8 ta belgidan iborat bo'lishi shart!")
        users_db[data.username]["password"] = data.new_password
        return {"status": "success", "message": "Parol yangilandi"}
    raise HTTPException(status_code=404, detail="User topilmadi")


@app.get("/api/admin/download-file/{file_id}")
async def download_user_file(file_id: int):
    file_item = next((f for f in uploaded_files_history if f.get("id") == file_id), None)
    if file_item:
        f_path = file_item["filepath"]
        if os.path.exists(f_path):
            return FileResponse(f_path, filename=file_item["filename"])
    raise HTTPException(status_code=404, detail="Fayl topilmadi")


# ==========================================
# 📊 BAZA TAHLILI
# ==========================================
@app.post("/api/analyze")
async def analyze_file(file: UploadFile = File(...), username: str = Form("Anonim")):
    global CURRENT_DATA
    try:
        contents = await file.read()
        analyzer = SmartDataAnalyzer(contents, file.filename)
        CURRENT_DATA = analyzer.analyze()
        CURRENT_DATA["uploaded_by"] = username  # Yuklagan user biriktiriladi

        saved_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)
        with open(file_path, "wb") as f:
            f.write(contents)

        file_size_kb = round(len(contents) / 1024, 2)
        uploaded_files_history.append({
            "id": len(uploaded_files_history),
            "filename": file.filename,
            "filepath": file_path,
            "username": username,
            "size": f"{file_size_kb} KB",
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M')
        })

        return {"status": "success", "data": CURRENT_DATA}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/export/png")
async def export_png():
    if not CURRENT_DATA:
        raise HTTPException(status_code=400, detail="Avval baza yuklang")
    path = HDExporter.generate_4k_png(CURRENT_DATA)
    return FileResponse(path, media_type="image/png", filename="Analytics_4K_Dashboard.png")


@app.get("/api/export/video")
async def export_video():
    if not CURRENT_DATA:
        raise HTTPException(status_code=400, detail="Avval baza yuklang")
    video_path = HDExporter.generate_4k_video(CURRENT_DATA)
    return FileResponse(video_path, media_type="video/mp4", filename="Analytics_4K_Animated.mp4")


# ==========================================
# 💬 CHAT LOGIKASI
# ==========================================
@app.websocket("/api/chat/ws")
async def chat_websocket(websocket: WebSocket):
    global admin_status
    await websocket.accept()
    active_websockets.append(websocket)
    await websocket.send_text(json.dumps({"type": "status", "status": admin_status}))

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            time_now = datetime.now().strftime("%H:%M")

            if BOT_TOKEN != "SIZNING_BOT_TOKENINGIZ":
                async with httpx.AsyncClient() as client:
                    msg_type = data.get("type")

                    if msg_type == "text":
                        msg_text = data.get("text")
                        username = data.get("username", "Mijoz")
                        if admin_status == "online":
                            await client.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                json={"chat_id": ADMIN_ID, "text": f"🌐 @{username} ({time_now}):\n\n{msg_text}"}
                            )
                        else:
                            missed_messages.append(f"[{time_now}] 📩 @{username}: {msg_text}")

                    elif msg_type == "file":
                        file_b64 = data.get("file_data")
                        file_name = data.get("file_name", "file")
                        mime_type = data.get("mime_type", "")
                        username = data.get("username", "Mijoz")
                        file_bytes = base64.b64decode(file_b64)

                        if admin_status == "online":
                            if "image" in mime_type:
                                endpoint, field = "sendPhoto", "photo"
                            elif "video" in mime_type:
                                endpoint, field = "sendVideo", "video"
                            else:
                                endpoint, field = "sendDocument", "document"

                            files = {field: (file_name, file_bytes, mime_type)}
                            data_payload = {'chat_id': ADMIN_ID,
                                            'caption': f"🌐 @{username} fayl ({time_now}): {file_name}"}
                            await client.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}",
                                data=data_payload,
                                files=files
                            )
                        else:
                            missed_messages.append(f"[{time_now}] 📁 @{username}: {file_name}")

    except WebSocketDisconnect:
        active_websockets.remove(websocket)


async def poll_telegram():
    global last_update_id, admin_status, missed_messages
    while True:
        if BOT_TOKEN == "SIZNING_BOT_TOKENINGIZ":
            await asyncio.sleep(5)
            continue
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=10",
                    timeout=15)
                if res.status_code == 200:
                    updates = res.json().get("result", [])
                    for result in updates:
                        last_update_id = result["update_id"]
                        msg = result.get("message", {})
                        chat_id = str(msg.get("chat", {}).get("id"))

                        if chat_id == str(ADMIN_ID):
                            text = msg.get("text", "")
                            photo = msg.get("photo")
                            video = msg.get("video")
                            document = msg.get("document")

                            if text == "/start":
                                payload = {
                                    "chat_id": ADMIN_ID,
                                    "text": "Admin paneli faol. Holatingizni tanlang:",
                                    "reply_markup": {
                                        "keyboard": [[{"text": "🟢 Onlayn"}, {"text": "🔴 Oflayn"}]],
                                        "resize_keyboard": True
                                    }
                                }
                                await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)

                            elif text == "🟢 Onlayn":
                                admin_status = "online"
                                for ws in active_websockets:
                                    await ws.send_text(json.dumps({"type": "status", "status": "online"}))
                                if missed_messages:
                                    bulk_text = "Oflayn vaqtdagi xabarlar:\n\n" + "\n".join(missed_messages)
                                    await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                                      json={"chat_id": ADMIN_ID, "text": bulk_text})
                                    missed_messages.clear()
                                else:
                                    await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                                      json={"chat_id": ADMIN_ID, "text": "Onlaynsiz."})

                            elif text == "🔴 Oflayn":
                                admin_status = "offline"
                                for ws in active_websockets:
                                    await ws.send_text(json.dumps({"type": "status", "status": "offline"}))
                                await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                                  json={"chat_id": ADMIN_ID, "text": "Oflaynsiz."})

                            elif text:
                                for ws in active_websockets:
                                    await ws.send_text(json.dumps({"type": "message", "text": text}))

                            elif photo:
                                file_id = photo[-1].get("file_id")
                                file_res = await client.get(
                                    f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
                                if file_res.status_code == 200:
                                    file_path = file_res.json().get("result", {}).get("file_path")
                                    img_res = await client.get(
                                        f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
                                    if img_res.status_code == 200:
                                        img_b64 = base64.b64encode(img_res.content).decode('utf-8')
                                        for ws in active_websockets:
                                            await ws.send_text(json.dumps({"type": "image", "image": img_b64}))

                            elif video:
                                file_id = video.get("file_id")
                                file_res = await client.get(
                                    f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
                                if file_res.status_code == 200:
                                    file_path = file_res.json().get("result", {}).get("file_path")
                                    vid_res = await client.get(
                                        f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
                                    if vid_res.status_code == 200:
                                        vid_b64 = base64.b64encode(vid_res.content).decode('utf-8')
                                        for ws in active_websockets:
                                            await ws.send_text(json.dumps({"type": "video", "video": vid_b64}))

                            elif document:
                                file_id = document.get("file_id")
                                file_name = document.get("file_name", "fayl")
                                file_res = await client.get(
                                    f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
                                if file_res.status_code == 200:
                                    file_path = file_res.json().get("result", {}).get("file_path")
                                    doc_res = await client.get(
                                        f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
                                    if doc_res.status_code == 200:
                                        doc_b64 = base64.b64encode(doc_res.content).decode('utf-8')
                                        for ws in active_websockets:
                                            await ws.send_text(
                                                json.dumps({"type": "file", "file": doc_b64, "name": file_name}))

        except Exception as e:
            print("Telegram Error:", e)
        await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_telegram())


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

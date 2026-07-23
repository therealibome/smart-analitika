import os
import io
import gc
import json
import random
import base64
import tempfile
import httpx
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse

# Matplotlib headless (server) rejimida
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = FastAPI(title="Smart Analytics Live Chat Backend")

# ==========================================
# 1. 🌐 CORS SOZLAMASI
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🤖 TELEGRAM BOT SOZLAMALARI
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8936728709:AAFeq1IgWiLG7Gh9Cs1DsYfwE-oRgxaSHkI")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "6758258778")
SERVER_URL = "https://smart-analitikabyklv.onrender.com"

# Active WebSocket xaritasi: { "username_lowercase": websocket_connection }
user_connections: Dict[str, WebSocket] = {}
last_active_user: Optional[str] = None


# ==========================================
# 🔗 TELEGRAM WEBHOOK (Startup)
# ==========================================
@app.on_event("startup")
async def setup_telegram_webhook():
    """Server ishga tushganida Telegram Webhook-ni ulaydi"""
    if BOT_TOKEN and "O'ZINGIZNING" not in BOT_TOKEN:
        webhook_endpoint = f"{SERVER_URL}/api/telegram-webhook"
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_endpoint}"
        async with httpx.AsyncClient() as client:
            try:
                res = await client.get(url)
                print(f"🔗 Telegram Webhook status: {res.json()}")
            except Exception as e:
                print(f"❌ Webhook error: {e}")


@app.get("/api/set-webhook")
async def manual_set_webhook():
    """Qo'lda Webhook-ni qayta ulash faydali liniyasi"""
    webhook_endpoint = f"{SERVER_URL}/api/telegram-webhook"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_endpoint}"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        return res.json()


# ==========================================
# 📩 TELEGRAM YORDAMCHI FUNKSIYALARI
# ==========================================
async def send_tg_text(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as e:
            print(f"❌ Telegram Text Error: {e}")


async def send_tg_media(chat_id: str, file_bytes: bytes, filename: str, mime_type: str, username: str):
    endpoint = "sendDocument"
    field = "document"

    if mime_type.startswith("image/"):
        endpoint = "sendPhoto"
        field = "photo"
    elif mime_type.startswith("video/"):
        endpoint = "sendVideo"
        field = "video"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                url,
                data={"chat_id": chat_id, "caption": f"📁 <b>Saytdan fayl</b>\n👤 User: /<code>{username}</code>"},
                files={field: (filename, file_bytes, mime_type)}
            )
        except Exception as e:
            print(f"❌ Telegram Media Error: {e}")


async def get_tg_file_url(file_id: str) -> str:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url)
            if res.status_code == 200:
                file_path = res.json()["result"]["file_path"]
                return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        except Exception as e:
            print(f"❌ File URL Error: {e}")
    return ""


def parse_admin_command(raw_text: str):
    """Admin kiritgan /username va xabar matnini ajratib beradi"""
    if not raw_text:
        return None, ""
    parts = raw_text.strip().split(maxsplit=1)
    first_word = parts[0]

    if first_word.startswith("/") or first_word.startswith("@"):
        target_username = first_word.lstrip("/@").strip().lower()
        clean_text = parts[1] if len(parts) > 1 else ""
        return target_username, clean_text

    return None, raw_text


# ==========================================
# 🗄 BAZA VA AUTH
# ==========================================
user_data_store: Dict[str, pd.DataFrame] = {}
users_db: Dict[str, str] = {}
uploaded_files_db: List[dict] = []
admin_otp_store: Dict[str, str] = {}


@app.post("/api/register")
async def register(data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Parol kamida 8 ta belgidan iborat bo'lishi shart!")
    if username in users_db:
        raise HTTPException(status_code=400, detail="Bu username allaqachon ro'yxatdan o'tgan!")
    users_db[username] = password
    return {"status": "success", "message": "Muvaffaqiyatli ro'yxatdan o'tildi"}


@app.post("/api/login")
async def login(data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if username not in users_db or users_db[username] != password:
        raise HTTPException(status_code=400, detail="Username yoki parol xato!")
    return {"status": "success", "username": username}


@app.post("/api/admin/request-otp")
async def request_otp():
    otp_code = str(random.randint(100000, 999999))
    admin_otp_store["current_otp"] = otp_code
    msg = f"🔐 <b>Smart Analytics Admin</b>\nKirish kodi: <code>{otp_code}</code>"
    await send_tg_text(ADMIN_CHAT_ID, msg)
    return {"status": "success", "message": "Kod Telegramga yuborildi!"}


@app.post("/api/admin/verify-otp")
async def verify_otp(data: dict):
    if admin_otp_store.get("current_otp") == data.get("otp", "").strip():
        admin_otp_store.pop("current_otp", None)
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Tasdiqlash kodi xato!")


@app.get("/api/admin/data")
async def get_admin_data():
    return {
        "status": "success",
        "users": [{"username": u, "registered_at": "2026-07-24"} for u in users_db.keys()],
        "files": uploaded_files_db
    }


# ==========================================
# 📊 ANALITIKA VA EXPORT
# ==========================================
@app.post("/api/analyze")
async def analyze_data(file: UploadFile = File(...), username: str = Form(...)):
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents)) if file.filename.endswith('.csv') else pd.read_excel(
            io.BytesIO(contents))

        cols = df.columns.tolist()
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        rev_col = num_cols[0] if num_cols else cols[-1]
        prod_col, seller_col, cat_col = cols[0], cols[1] if len(cols) > 1 else cols[0], cols[2] if len(cols) > 2 else \
        cols[0]

        user_data_store[username] = df
        uploaded_files_db.append({"id": len(uploaded_files_db) + 1, "filename": file.filename, "username": username,
                                  "size": f"{round(len(contents) / 1024, 1)} KB"})

        return {
            "status": "success",
            "data": {
                "metadata": {"revenue_title": rev_col, "product_title": prod_col, "seller_title": seller_col,
                             "category_title": cat_col},
                "kpi": {"total_revenue": float(df[rev_col].sum()), "transactions": int(len(df)),
                        "avg_check": float(df[rev_col].mean()),
                        "top_product": str(df.groupby(prod_col)[rev_col].sum().idxmax()),
                        "top_seller": str(df.groupby(seller_col)[rev_col].sum().idxmax())},
                "product_col": prod_col, "revenue_col": rev_col,
                "pareto": df.groupby(prod_col)[rev_col].sum().reset_index().sort_values(by=rev_col,
                                                                                        ascending=False).head(
                    10).to_dict(orient='records'),
                "sellers": [{"seller": str(r[seller_col]), "actual": float(r[rev_col]),
                             "target": round(float(r[rev_col]) * 1.15, 2)} for _, r in
                            df.groupby(seller_col)[rev_col].sum().reset_index().head(5).iterrows()],
                "categories": [{"name": str(r[cat_col]), "value": float(r[rev_col])} for _, r in
                               df.groupby(cat_col)[rev_col].sum().reset_index().head(5).iterrows()],
                "kde": {"x": [str(round(b, 1)) for b in np.histogram(df[rev_col].dropna(), bins=10)[1][:-1]],
                        "y": [int(h) for h in np.histogram(df[rev_col].dropna(), bins=10)[0]]},
                "table_columns": cols[:6], "table_data": df.head(15).astype(str).to_dict(orient='records')
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Xatolik: {str(e)}")


@app.get("/api/export/png")
async def export_png(username: Optional[str] = None):
    if not username or username not in user_data_store: raise HTTPException(status_code=400,
                                                                            detail="Avval baza yuklang!")
    df = user_data_store[username]
    rev_col = df.select_dtypes(include=[np.number]).columns[0]
    fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
    top_df = df.groupby(df.columns[0])[rev_col].sum().sort_values(ascending=False).head(8)
    ax.bar(top_df.index.astype(str), top_df.values, color='#2563EB')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120)
    plt.close(fig)
    gc.collect()
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/export/video")
async def export_video(username: Optional[str] = None):
    if not username or username not in user_data_store: raise HTTPException(status_code=400,
                                                                            detail="Avval baza yuklang!")
    import imageio
    df = user_data_store[username]
    rev_col = df.select_dtypes(include=[np.number]).columns[0]
    top_df = df.groupby(df.columns[0])[rev_col].sum().sort_values(ascending=False).head(7)
    x_names, y_final, frames = [str(n)[:10] for n in top_df.index], top_df.values, []

    for i in range(1, 13):
        fig, ax = plt.subplots(figsize=(7, 4), dpi=85)
        ax.bar(x_names, y_final * (i / 12), color='#2563EB', width=0.5)
        ax.set_ylim(0, max(y_final) * 1.15)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=85)
        plt.close(fig)
        buf.seek(0)
        frames.append(imageio.v2.imread(buf))
        buf.close()

    plt.close('all')
    gc.collect()
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    imageio.mimsave(temp_file.name, frames, fps=8, codec='libx264')
    temp_file.close()
    return FileResponse(temp_file.name, media_type="video/mp4", filename="Analytics_Animated.mp4")


# ==========================================
# 💬 REALTIME LIVE CHAT (Sayt -> Telegram Bot)
# ==========================================

@app.websocket("/api/chat/ws")
async def websocket_chat(websocket: WebSocket):
    global last_active_user
    await websocket.accept()
    current_username = None
    try:
        await websocket.send_json({"type": "status", "status": "online"})
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            raw_username = msg.get("username", "Anonim").strip()
            username_key = raw_username.lower()

            current_username = username_key
            user_connections[username_key] = websocket
            last_active_user = username_key

            msg_type = msg.get("type")

            # Saytdan kelgan matn
            if msg_type == "text":
                text = msg.get("text", "")
                caption = f"💬 <b>Saytdan xabar</b>\n👤 User: /<code>{raw_username}</code>\n\n📝 {text}"
                await send_tg_text(ADMIN_CHAT_ID, caption)

            # Saytdan kelgan fayl/media
            elif msg_type == "file":
                file_name = msg.get("file_name", "file")
                mime_type = msg.get("mime_type", "application/octet-stream")
                b64_data = msg.get("file_data", "")
                file_bytes = base64.b64decode(b64_data)

                await send_tg_media(ADMIN_CHAT_ID, file_bytes, file_name, mime_type, raw_username)

    except WebSocketDisconnect:
        if current_username and current_username in user_connections:
            del user_connections[current_username]


# ==========================================
# 📥 TELEGRAM WEBHOOK (Telegram Bot -> Sayt User)
# ==========================================
@app.post("/api/telegram-webhook")
async def telegram_webhook(request: Request):
    """Admin kiritgan xabarni mos keluvchi sayt foydalanuvchisiga uzatadi"""
    try:
        data = await request.json()
        message = data.get("message", {})

        raw_text = message.get("text") or message.get("caption") or ""
        parsed_target, clean_text = parse_admin_command(raw_text)

        # Agar /username yozilgan bo'lsa o'shanga, yozilmagan bo'lsa oxirgi aktiv userga yuboradi
        target_username = parsed_target if parsed_target else last_active_user

        if target_username and target_username in user_connections:
            ws = user_connections[target_username]

            # 1. Matnli xabar
            if "text" in message and clean_text:
                await ws.send_json({"type": "message", "text": clean_text})
                await send_tg_text(ADMIN_CHAT_ID, f"✅ @{target_username} ga yuborildi.")

            # 2. Rasm
            elif "photo" in message:
                photo = message["photo"][-1]
                img_url = await get_tg_file_url(photo["file_id"])
                if img_url:
                    await ws.send_json({"type": "image", "image": img_url})
                    await send_tg_text(ADMIN_CHAT_ID, f"🖼 ✅ @{target_username} ga rasm yuborildi.")

            # 3. Video
            elif "video" in message:
                vid_url = await get_tg_file_url(message["video"]["file_id"])
                if vid_url:
                    await ws.send_json({"type": "video", "video": vid_url})
                    await send_tg_text(ADMIN_CHAT_ID, f"🎥 ✅ @{target_username} ga video yuborildi.")

            # 4. Hujjat / Fayl
            elif "document" in message:
                doc = message["document"]
                doc_url = await get_tg_file_url(doc["file_id"])
                if doc_url:
                    await ws.send_json({"type": "file", "name": doc.get("file_name", "Fayl"), "file": doc_url})
                    await send_tg_text(ADMIN_CHAT_ID, f"📁 ✅ @{target_username} ga fayl yuborildi.")
        else:
            if target_username:
                await send_tg_text(ADMIN_CHAT_ID,
                                   f"❌ <b>@{target_username}</b> hozir saytda emas (oflayn yoki ulagich uzilgan).")
            else:
                await send_tg_text(ADMIN_CHAT_ID, "⚠️ Hozircha hech qanday foydalanuvchi online emas.")

    except Exception as e:
        print(f"❌ Webhook Error: {e}")

    return {"status": "ok"}
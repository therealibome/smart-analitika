import os
import io
import gc
import json
import random
import tempfile
import httpx
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse

# Matplotlib-ni server rejimida ishlatish (GUI ekrani ochilmasligi uchun)
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = FastAPI(title="Smart Analytics Pro Backend")

# ==========================================
# 1. 🌐 CORS SOZLAMASI (Failed to fetch oldini oladi)
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🤖 TELEGRAM BOT SOZLAMALARI (Sinov uchun to'g'ridan-to'g'ri)
# ==========================================
BOT_TOKEN = "8936728709:AAFeq1IgWiLG7Gh9Cs1DsYfwE-oRgxaSHkI"  # 👈 BotFather bergan TO'LIQ tokeningizni yozing
ADMIN_CHAT_ID = "6758258778"  # 👈 @userinfobot bergan ID-ingizni yozing


async def send_telegram_message(chat_id: str, text: str):
    """Telegram bot orqali xabar yuboruvchi funksiya"""
    if not BOT_TOKEN:
        print("⚠️ Bot Token yo'q!")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            print(f"📡 Telegram javobi: {res.status_code} - {res.text}")  # Terminalda natijani ko'rish uchun
            return res.status_code == 200
        except Exception as e:
            print(f"❌ Telegram xatolik: {e}")
            return False


# ==========================================
# 🗄 XOTIRADAGI VAQTINCHALIK BAZALAR
# ==========================================
user_data_store: Dict[str, pd.DataFrame] = {}
users_db: Dict[str, str] = {}  # username: password
uploaded_files_db: List[dict] = []
admin_otp_store: Dict[str, str] = {}
active_connections: List[WebSocket] = []


# ==========================================
# 🔑 AUTHENTICATION & ADMIN ENDPOINTS
# ==========================================

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

    msg = (
        "🔐 <b>Smart Analytics Admin Panel</b>\n\n"
        "Kirish uchun tasdiqlash kodi:\n"
        f"👉 <code>{otp_code}</code>\n\n"
        "⚠️ Kodni hech kimga bermang!"
    )

    sent = await send_telegram_message(ADMIN_CHAT_ID, msg)
    if not sent:
        print(f"🔑 GENERATED OTP KOD: {otp_code}")

    return {"status": "success", "message": "Kod Telegramga yuborildi!"}


@app.post("/api/admin/verify-otp")
async def verify_otp(data: dict):
    user_otp = data.get("otp", "").strip()
    real_otp = admin_otp_store.get("current_otp")

    if real_otp and user_otp == real_otp:
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


@app.delete("/api/admin/delete-user/{username}")
async def delete_user(username: str):
    if username in users_db:
        del users_db[username]
        if username in user_data_store:
            del user_data_store[username]
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi!")


@app.post("/api/admin/reset-password")
async def reset_password(data: dict):
    username = data.get("username", "").strip()
    new_password = data.get("password", "").strip()
    if username in users_db and len(new_password) >= 8:
        users_db[username] = new_password
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Xatolik yuz berdi!")


# ==========================================
# 📊 DATA ANALYSIS ENDPOINT
# ==========================================

@app.post("/api/analyze")
async def analyze_data(file: UploadFile = File(...), username: str = Form(...)):
    try:
        contents = await file.read()
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))

        cols = df.columns.tolist()
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        rev_col = num_cols[0] if num_cols else cols[-1]
        prod_col = cols[0]
        seller_col = cols[1] if len(cols) > 1 else cols[0]
        cat_col = cols[2] if len(cols) > 2 else cols[0]

        user_data_store[username] = df

        uploaded_files_db.append({
            "id": len(uploaded_files_db) + 1,
            "filename": file.filename,
            "username": username,
            "size": f"{round(len(contents) / 1024, 1)} KB"
        })

        total_rev = float(df[rev_col].sum())
        tx_count = int(len(df))
        avg_check = float(df[rev_col].mean())

        top_p = str(df.groupby(prod_col)[rev_col].sum().idxmax())
        top_s = str(df.groupby(seller_col)[rev_col].sum().idxmax())

        pareto_df = df.groupby(prod_col)[rev_col].sum().reset_index().sort_values(by=rev_col, ascending=False).head(10)
        pareto_data = pareto_df.to_dict(orient='records')

        sellers_df = df.groupby(seller_col)[rev_col].sum().reset_index().head(5)
        sellers_data = []
        for _, row in sellers_df.iterrows():
            act = float(row[rev_col])
            sellers_data.append({
                "seller": str(row[seller_col]),
                "actual": act,
                "target": round(act * 1.15, 2)
            })

        cat_df = df.groupby(cat_col)[rev_col].sum().reset_index().head(5)
        cat_data = [{"name": str(r[cat_col]), "value": float(r[rev_col])} for _, r in cat_df.iterrows()]

        hist, bin_edges = np.histogram(df[rev_col].dropna(), bins=10)
        kde_x = [str(round(b, 1)) for b in bin_edges[:-1]]
        kde_y = [int(h) for h in hist]

        return {
            "status": "success",
            "data": {
                "metadata": {
                    "revenue_title": rev_col,
                    "product_title": prod_col,
                    "seller_title": seller_col,
                    "category_title": cat_col
                },
                "kpi": {
                    "total_revenue": total_rev,
                    "transactions": tx_count,
                    "avg_check": avg_check,
                    "top_product": top_p,
                    "top_seller": top_s
                },
                "product_col": prod_col,
                "revenue_col": rev_col,
                "pareto": pareto_data,
                "sellers": sellers_data,
                "categories": cat_data,
                "kde": {"x": kde_x, "y": kde_y},
                "table_columns": cols[:6],
                "table_data": df.head(15).astype(str).to_dict(orient='records')
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fayl tahlilida xatolik: {str(e)}")


# ==========================================
# 📸 PNG EXPORT (Low RAM)
# ==========================================

@app.get("/api/export/png")
async def export_png(username: Optional[str] = None):
    if not username or username not in user_data_store:
        raise HTTPException(status_code=400, detail="Avval baza yuklang!")

    df = user_data_store[username]
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    rev_col = num_cols[0] if num_cols else df.columns[-1]
    prod_col = df.columns[0]

    fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
    top_df = df.groupby(prod_col)[rev_col].sum().sort_values(ascending=False).head(8)

    ax.bar(top_df.index.astype(str), top_df.values, color='#2563EB')
    ax.set_title(f"Top Mahsulotlar — {rev_col}", fontsize=14, fontweight='bold')
    plt.xticks(rotation=25, ha='right')
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120)
    plt.close(fig)
    gc.collect()

    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


# ==========================================
# 🎬 VIDEO EXPORT (RAM Optimized for Render)
# ==========================================

@app.get("/api/export/video")
async def export_video(username: Optional[str] = None):
    if not username or username not in user_data_store:
        raise HTTPException(status_code=400, detail="Avval baza yuklang!")

    try:
        import imageio
        df = user_data_store[username]
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        rev_col = num_cols[0] if num_cols else df.columns[-1]
        prod_col = df.columns[0]

        top_df = df.groupby(prod_col)[rev_col].sum().sort_values(ascending=False).head(7)
        x_names = [str(n)[:10] for n in top_df.index]
        y_final = top_df.values

        frames = []
        num_frames = 12

        for i in range(1, num_frames + 1):
            progress = i / num_frames
            current_y = y_final * progress

            fig, ax = plt.subplots(figsize=(7, 4), dpi=85)
            ax.bar(x_names, current_y, color='#2563EB', width=0.5)
            ax.set_ylim(0, max(y_final) * 1.15)
            ax.set_title("Sotuvlar Dinamikasi", fontsize=11, fontweight='bold')
            plt.xticks(rotation=15, ha='right', fontsize=8)
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=85)
            plt.close(fig)

            buf.seek(0)
            img = imageio.v2.imread(buf)
            frames.append(img)
            buf.close()

        plt.close('all')
        gc.collect()

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        imageio.mimsave(temp_file.name, frames, fps=8, codec='libx264')
        temp_file.close()

        return FileResponse(
            temp_file.name,
            media_type="video/mp4",
            filename="Analytics_Animated.mp4"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video tayyorlashda xatolik: {str(e)}")


# ==========================================
# 💬 CHAT WEBSOCKET (Telegram Botga Yuborish)
# ==========================================

@app.websocket("/api/chat/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        await websocket.send_json({"type": "status", "status": "online"})
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            user_text = msg.get("text", "Fayl/Media yuborildi")
            username = msg.get("username", "Anonim")

            # 📲 Telegram Bot orqali shaxsiy admin chatiga habar boradi
            tg_message = (
                "💬 <b>Saytdan Yangi Xabar!</b>\n\n"
                f"👤 <b>Kimdan:</b> @{username}\n"
                f"📝 <b>Xabar:</b> {user_text}"
            )
            await send_telegram_message(ADMIN_CHAT_ID, tg_message)

            # Saytdagi chat oynasiga tasdiq xabari qaytaramiz
            await websocket.send_json({
                "type": "message",
                "text": "Xabaringiz adminga yetkazildi! Tez orada javob beramiz."
            })

    except WebSocketDisconnect:
        active_connections.remove(websocket)
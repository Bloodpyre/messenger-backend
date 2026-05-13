import json
import asyncio
import sqlite3
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ========== НАСТРОЙКА БАЗЫ ДАННЫХ ==========
# Определяем правильный путь для БД в зависимости от окружения
def get_db_path():
    """Возвращает правильный путь для файла базы данных"""
    # Для Amvera: используем постоянное хранилище /data
    if os.path.exists('/data') or os.getenv('AMVERA'):
        db_path = '/data/messenger.db'
        print(f"🟢 Режим Amvera: база данных будет в {db_path}")
    else:
        # Для локальной разработки
        db_path = 'messenger.db'
        print(f"🟡 Локальный режим: база данных будет в {db_path}")
    return db_path


DATABASE_FILE = get_db_path()


def get_db_connection():
    """Создаёт соединение с SQLite базой данных"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы при первом запуске"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            encrypted_text TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print(f"✅ База данных SQLite инициализирована: {DATABASE_FILE}")


# ========== PYDANTIC МОДЕЛИ ==========
class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class MessageSend(BaseModel):
    recipient: str
    encrypted_text: str
    sender: str


# ========== WEBSOCKET МЕНЕДЖЕР ==========
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections[username] = websocket
        print(f"✅ {username} подключился через WebSocket")

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]
            print(f"❌ {username} отключился")

    async def send_personal_message(self, message: dict, username: str):
        if username in self.active_connections:
            try:
                await self.active_connections[username].send_text(json.dumps(message))
                return True
            except Exception as e:
                print(f"Ошибка отправки {username}: {e}")
        return False


# ========== LIFESPAN ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запуск сервера...")
    init_db()
    yield
    print("🛑 Сервер остановлен")


# ========== ПРИЛОЖЕНИЕ FASTAPI ==========
app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== ЭНДПОИНТЫ ==========
@app.get("/")
def root():
    return {"message": "Messenger API работает с SQLite и WebSocket!"}


@app.post("/register")
async def register(user: UserRegister):
    """Регистрация нового пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (user.username, user.password))
        conn.commit()
        return {"status": "ok", "username": user.username}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    finally:
        conn.close()


@app.post("/login")
async def login(user: UserLogin):
    """Вход пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username = ?", (user.username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if row["password"] != user.password:
        raise HTTPException(status_code=401, detail="Неверный пароль")
    return {"status": "ok", "username": user.username}


@app.get("/users")
async def get_users():
    """Список всех пользователей"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [{"username": row["username"]} for row in rows]


@app.get("/messages/{username}")
async def get_messages(username: str):
    """История сообщений пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender, recipient, encrypted_text, timestamp
        FROM messages
        WHERE sender = ? OR recipient = ?
        ORDER BY timestamp ASC
    """, (username, username))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "message_id": str(row["id"]),
            "sender": row["sender"],
            "recipient": row["recipient"],
            "encrypted_text": row["encrypted_text"],
            "timestamp": row["timestamp"]
        }
        for row in rows
    ]


@app.post("/messages")
async def save_message_api(message: MessageSend):
    """HTTP-эндпоинт для сохранения сообщения (запасной)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (sender, recipient, encrypted_text)
        VALUES (?, ?, ?)
    """, (message.sender, message.recipient, message.encrypted_text))
    conn.commit()
    conn.close()
    return {"status": "sent"}

@app.get("/debug/reset_messages")
async def reset_messages():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Удаляем старую таблицу
    cursor.execute("DROP TABLE IF EXISTS messages")
    # Создаём новую с AUTOINCREMENT
    cursor.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            encrypted_text TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Таблица messages пересоздана"}

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(websocket, username)

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            recipient = message_data.get("recipient")
            encrypted_text = message_data.get("encrypted_text")
            sender = username

            # Сохраняем в базу
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO messages (sender, recipient, encrypted_text)
                VALUES (?, ?, ?)
            """, (sender, recipient, encrypted_text))
            conn.commit()
            conn.close()

            # Отправляем получателю, если он онлайн
            await manager.send_personal_message({
                "sender": sender,
                "encrypted_text": encrypted_text
            }, recipient)

            print(f"📨 Сообщение от {sender} -> {recipient}")


    except WebSocketDisconnect:
        manager.disconnect(username)


# ========== ЗАПУСК ДЛЯ AMVERA ==========
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 80))
    uvicorn.run(app, host="0.0.0.0", port=port)
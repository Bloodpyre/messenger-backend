import json
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List

import psycopg2
from psycopg2 import pool
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bloodpyre:qwerty123456@localhost:5432/messenger")

# Парсим DATABASE_URL
import urllib.parse

result = urllib.parse.urlparse(DATABASE_URL)
db_params = {
    "user": result.username,
    "password": result.password,
    "host": result.hostname,
    "port": result.port or 5432,
    "database": result.path[1:]
}

# Создаем пул соединений
db_pool = None


# Модели
class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


# Менеджер WebSocket соединений
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections[username] = websocket
        print(f"✅ {username} подключился")

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]
            print(f"❌ {username} отключился")

    async def send_personal_message(self, message: dict, username: str):
        if username in self.active_connections:
            try:
                await self.active_connections[username].send_text(json.dumps(message))
                return True
            except:
                return False
        return False


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    # Создаем пул соединений PostgreSQL
    db_pool = pool.SimpleConnectionPool(1, 10, **db_params)
    print("🚀 Сервер запущен, пул PostgreSQL создан")

    # Создаем таблицы
    await asyncio.to_thread(init_db)

    yield

    # Закрываем пул при остановке
    if db_pool:
        db_pool.closeall()
    print("🛑 Сервер остановлен")


def init_db():
    """Создает таблицы (синхронная функция)"""
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    encrypted_text TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
            print("✅ Таблицы созданы/проверены")
    finally:
        db_pool.putconn(conn)


def get_user(username: str):
    """Проверяет существование пользователя"""
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            return cur.fetchone() is not None
    finally:
        db_pool.putconn(conn)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Messenger API с PostgreSQL и WebSocket!"}


@app.post("/register")
async def register(user: UserRegister):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (user.username, user.password)
            )
            conn.commit()
            return {"status": "ok", "username": user.username}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    finally:
        db_pool.putconn(conn)


@app.post("/login")
async def login(user: UserLogin):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password FROM users WHERE username = %s",
                (user.username,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            if row[0] != user.password:
                raise HTTPException(status_code=401, detail="Неверный пароль")
            return {"status": "ok", "username": user.username}
    finally:
        db_pool.putconn(conn)


@app.get("/users")
async def get_users():
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users")
            rows = cur.fetchall()
            return [{"username": row[0]} for row in rows]
    finally:
        db_pool.putconn(conn)


@app.get("/messages/{username}")
async def get_messages(username: str):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sender, recipient, encrypted_text, timestamp
                FROM messages
                WHERE sender = %s OR recipient = %s
                ORDER BY timestamp ASC
            """, (username, username))
            rows = cur.fetchall()
            return [
                {
                    "sender": row[0],
                    "recipient": row[1],
                    "encrypted_text": row[2],
                    "timestamp": row[3].isoformat()
                }
                for row in rows
            ]
    finally:
        db_pool.putconn(conn)


@app.post("/messages")
async def save_message_api(message: dict):
    """HTTP-эндпоинт для сохранения сообщения (запасной)"""
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO messages (sender, recipient, encrypted_text)
                VALUES (%s, %s, %s)
            """, (message["sender"], message["recipient"], message["encrypted_text"]))
            conn.commit()
            return {"status": "sent"}
    finally:
        db_pool.putconn(conn)


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
            conn = db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO messages (sender, recipient, encrypted_text)
                        VALUES (%s, %s, %s)
                    """, (sender, recipient, encrypted_text))
                    conn.commit()
            finally:
                db_pool.putconn(conn)

            # Отправляем получателю, если он онлайн
            await manager.send_personal_message({
                "sender": sender,
                "encrypted_text": encrypted_text
            }, recipient)

            print(f"📨 Сообщение от {sender} -> {recipient}")

    except WebSocketDisconnect:
        manager.disconnect(username)
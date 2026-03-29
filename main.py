from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict
import uuid
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="Messenger API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище пользователей: username -> {"password": str, "user_id": str}
users: Dict[str, dict] = {}
# Хранилище сообщений
messages: List[dict] = []


# ========== МОДЕЛИ ==========

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


class MessageResponse(BaseModel):
    sender: str
    recipient: str
    encrypted_text: str
    message_id: str
    timestamp: str


# ========== ЭНДПОИНТЫ ==========

@app.get("/")
def root():
    return {"message": "Messenger API работает!"}


@app.post("/register")
def register(user: UserRegister):
    """Регистрация нового пользователя с паролем"""
    if user.username in users:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    user_id = str(uuid.uuid4())[:8]
    users[user.username] = {
        "password": user.password,
        "user_id": user_id
    }
    print(f"✅ Зарегистрирован: {user.username} (пароль: {user.password})")
    return {"user_id": user_id, "username": user.username}


@app.post("/login")
def login(user: UserLogin):
    """Вход пользователя"""
    if user.username not in users:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if users[user.username]["password"] != user.password:
        raise HTTPException(status_code=401, detail="Неверный пароль")

    return {"status": "ok", "username": user.username}


@app.get("/users")
def get_users():
    """Список всех пользователей (без паролей)"""
    return [{"user_id": users[u]["user_id"], "username": u} for u in users.keys()]


@app.post("/messages")
def send_message(message: MessageSend):
    """Отправка сообщения"""
    if message.recipient not in users:
        raise HTTPException(status_code=404, detail="Получатель не найден")

    msg = {
        "message_id": str(uuid.uuid4())[:8],
        "recipient": message.recipient,
        "sender": message.sender,
        "encrypted_text": message.encrypted_text,
        "timestamp": datetime.now().isoformat()
    }
    messages.append(msg)
    print(f"📨 Сообщение от {message.sender} для {message.recipient}")
    return {"status": "sent", "message_id": msg["message_id"]}


@app.get("/messages/{username}", response_model=List[MessageResponse])
def get_messages(username: str):
    """Получение всех сообщений пользователя"""
    user_messages = []
    for msg in messages:
        if msg["recipient"] == username or msg["sender"] == username:
            user_messages.append(msg)

    user_messages.sort(key=lambda x: x.get("timestamp", ""))

    return [
        MessageResponse(
            sender=msg["sender"],
            recipient=msg["recipient"],
            encrypted_text=msg["encrypted_text"],
            message_id=msg["message_id"],
            timestamp=msg.get("timestamp", "")
        )
        for msg in user_messages
    ]


# ========== ЗАПУСК ==========
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 80))
    uvicorn.run(app, host="0.0.0.0", port=port)
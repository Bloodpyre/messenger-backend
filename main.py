from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uuid

app = FastAPI(title="Messenger API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Хранилище: user_id -> {username, public_key}
users: Dict[str, dict] = {}
# Хранилище сообщений
messages: List[dict] = []


# ========== МОДЕЛИ ДАННЫХ ==========

class UserRegister(BaseModel):
    username: str
    public_key: str  # ← обязательно!


class MessageSend(BaseModel):
    recipient: str
    encrypted_text: str


class MessageResponse(BaseModel):
    sender: str
    encrypted_text: str
    message_id: str


# ========== ЭНДПОИНТЫ ==========

@app.get("/")
def root():
    return {"message": "Messenger API работает!"}


@app.post("/register")
def register(user: UserRegister):
    """Регистрация с публичным ключом"""
    # Проверяем, существует ли пользователь
    for uid, data in users.items():
        if data["username"] == user.username:
            raise HTTPException(status_code=400, detail="Пользователь уже существует")

    user_id = str(uuid.uuid4())[:8]
    users[user_id] = {
        "username": user.username,
        "public_key": user.public_key
    }
    print(f"✅ Зарегистрирован: {user.username} с ключом {user.public_key[:50]}...")
    return {"user_id": user_id, "username": user.username}


@app.get("/users")
def get_users():
    """Список всех пользователей"""
    return [{"user_id": uid, "username": data["username"]} for uid, data in users.items()]


@app.get("/users/{username}/public_key")
def get_public_key(username: str):
    """Получить публичный ключ пользователя"""
    for uid, data in users.items():
        if data["username"] == username:
            return {"username": username, "public_key": data["public_key"]}
    raise HTTPException(status_code=404, detail="Пользователь не найден")


@app.post("/messages")
def send_message(message: MessageSend):
    """Отправка сообщения"""
    # Проверяем, существует ли получатель
    recipient_exists = False
    for data in users.values():
        if data["username"] == message.recipient:
            recipient_exists = True
            break

    if not recipient_exists:
        raise HTTPException(status_code=404, detail="Получатель не найден")

    msg = {
        "message_id": str(uuid.uuid4())[:8],
        "recipient": message.recipient,
        "sender": "unknown",  # позже добавим аутентификацию
        "encrypted_text": message.encrypted_text,
        "timestamp": datetime.now().isoformat()
    }
    messages.append(msg)
    print(f"📨 Сообщение сохранено для {message.recipient}")
    return {"status": "sent", "message_id": msg["message_id"]}


@app.get("/messages/{username}", response_model=List[MessageResponse])
def get_messages(username: str):
    #Получение всех сообщений для пользователя
    user_messages = []

    for msg in messages:
        if msg["recipient"] == username:
            user_messages.append(msg)

    user_messages.sort(key=lambda x: x.get("timestamp", ""))

    return [
        MessageResponse(
            sender=msg["sender"],
            encrypted_text=msg["encrypted_text"],
            message_id=msg["message_id"]
        )
        for msg in user_messages
    ]

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 80))
    uvicorn.run(app, host="0.0.0.0", port=port)
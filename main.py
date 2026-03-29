from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import uuid
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Messenger API")

# Добавляем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Хранилище пользователей (только username)
users: Dict[str, str] = {}  # user_id -> username
# Хранилище сообщений
messages: List[dict] = []


# ========== МОДЕЛИ ДАННЫХ ==========

class UserRegister(BaseModel):
    username: str  # ← только имя, без ключа


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
    """Регистрация нового пользователя"""
    if user.username in users.values():
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    user_id = str(uuid.uuid4())[:8]
    users[user_id] = user.username
    print(f"✅ Зарегистрирован: {user.username}")
    return {"user_id": user_id, "username": user.username}


@app.get("/users")
def get_users():
    """Список всех пользователей"""
    return [{"user_id": uid, "username": username} for uid, username in users.items()]


@app.post("/messages")
def send_message(message: MessageSend):
    """Отправка сообщения"""
    # Проверяем, существует ли получатель
    if message.recipient not in users.values():
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
    """Получение всех сообщений, где пользователь участвует"""
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

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 80))
    uvicorn.run(app, host="0.0.0.0", port=port)

#bruh
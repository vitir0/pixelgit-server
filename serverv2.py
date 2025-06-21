from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import os
import json
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Конфигурация
app.config['SECRET_KEY'] = 'pixelgit_secret_2025'
app.config['DATA_DIR'] = 'data'
app.config['BACKUP_DIR'] = 'backups'

# Создаем директории для данных
Path(app.config['DATA_DIR']).mkdir(exist_ok=True)
Path(app.config['BACKUP_DIR']).mkdir(exist_ok=True)

# Функции для работы с данными
def load_data(filename):
    filepath = os.path.join(app.config['DATA_DIR'], filename)
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return {}

def save_data(data, filename):
    filepath = os.path.join(app.config['DATA_DIR'], filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Создаем резервную копию
    backup_path = os.path.join(app.config['BACKUP_DIR'], f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}")
    with open(backup_path, 'w') as f:
        json.dump(data, f, indent=2)

# Загрузка данных при запуске
users = load_data('users.json')
chats = load_data('chats.json')
messages = load_data('messages.json')
encryption_keys = load_data('encryption_keys.json')

@app.route('/')
def index():
    return "PixelGit API is running"

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    user = users.get(username)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 401
    
    if not check_password_hash(user['password'], password):
        return jsonify({'success': False, 'message': 'Invalid password'}), 401
    
    # Создаем JWT токен
    payload = {
        'sub': username,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({
        'success': True,
        'token': token,
        'username': username
    }), 200

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    if username in users:
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    
    # Хешируем пароль
    hashed_password = generate_password_hash(password)
    user_id = str(uuid.uuid4())
    
    users[username] = {
        'id': user_id,
        'password': hashed_password,
        'chats': []
    }
    
    save_data(users, 'users.json')
    
    return jsonify({
        'success': True,
        'message': 'User registered successfully',
        'userId': user_id
    }), 201

@app.route('/users', methods=['GET'])
def get_users():
    # Возвращаем всех пользователей
    user_list = [
        {"id": user_data['id'], "username": username} 
        for username, user_data in users.items()
    ]
    print(f"Returning {len(user_list)} users")  # Отладочная информация
    return jsonify(user_list), 200

@app.route('/chats', methods=['POST'])
def create_chat():
    data = request.get_json()
    user1 = data.get('user1')
    user2 = data.get('user2')
    
    if not user1 or not user2:
        return jsonify({'success': False, 'message': 'Both users are required'}), 400
    
    # Проверяем существование пользователей
    if user1 not in users or user2 not in users:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    # Проверяем, существует ли уже чат
    for chat_id, chat in chats.items():
        if sorted(chat['participants']) == sorted([user1, user2]):
            return jsonify({
                'success': True,
                'message': 'Chat already exists',
                'chatId': chat_id
            }), 200
    
    # Создаем уникальный ID чата
    chat_id = str(uuid.uuid4())
    
    # Создаем чат
    chats[chat_id] = {
        'id': chat_id,
        'participants': [user1, user2],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_message': None,
        'last_message_time': None
    }
    
    # Добавляем чат пользователям
    users[user1]['chats'].append(chat_id)
    users[user2]['chats'].append(chat_id)
    
    save_data(users, 'users.json')
    save_data(chats, 'chats.json')
    
    return jsonify({
        'success': True,
        'message': 'Chat created successfully',
        'chatId': chat_id
    }), 201

@app.route('/chats/<username>', methods=['GET'])
def get_user_chats(username):
    if username not in users:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    user_chats = []
    for chat_id in users[username]['chats']:
        if chat_id in chats:
            chat = chats[chat_id]
            
            # Находим собеседника
            participants = chat['participants']
            other_user = participants[0] if participants[1] == username else participants[1]
            
            user_chats.append({
                'id': chat_id,
                'with_user': other_user,
                'last_message': chat['last_message'],
                'last_message_time': chat['last_message_time']
            })
    
    return jsonify({'success': True, 'chats': user_chats}), 200

@app.route('/chats/<chat_id>/key', methods=['GET', 'POST'])
def handle_encryption_key(chat_id):
    if request.method == 'GET':
        if chat_id in encryption_keys:
            return jsonify({'success': True, 'key': encryption_keys[chat_id]}), 200
        else:
            return jsonify({'success': False, 'message': 'Key not found'}), 404
    
    elif request.method == 'POST':
        data = request.get_json()
        key = data.get('key')
        
        if not key:
            return jsonify({'success': False, 'message': 'Key is required'}), 400
            
        encryption_keys[chat_id] = key
        save_data(encryption_keys, 'encryption_keys.json')
        return jsonify({'success': True, 'message': 'Encryption key saved'}), 200

@app.route('/messages', methods=['POST'])
def send_message():
    data = request.get_json()
    chat_id = data.get('chatId')
    sender = data.get('sender')
    text = data.get('text')
    
    if not chat_id or not sender or not text:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    if chat_id not in chats:
        return jsonify({'success': False, 'message': 'Chat not found'}), 404
    
    if sender not in chats[chat_id]['participants']:
        return jsonify({'success': False, 'message': 'User not in chat'}), 403
    
    # Создаем сообщение
    message_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if chat_id not in messages:
        messages[chat_id] = []
    
    messages[chat_id].append({
        'id': message_id,
        'sender': sender,
        'text': text,
        'timestamp': timestamp
    })
    
    # Обновляем последнее сообщение в чате
    chats[chat_id]['last_message'] = "🔒 Encrypted message"
    chats[chat_id]['last_message_time'] = timestamp
    
    save_data(chats, 'chats.json')
    save_data(messages, 'messages.json')
    
    return jsonify({
        'success': True,
        'message': 'Message sent successfully',
        'messageId': message_id
    }), 201

@app.route('/messages/<chat_id>', methods=['GET'])
def get_chat_messages(chat_id):
    if chat_id not in messages:
        return jsonify({'success': False, 'message': 'Chat not found'}), 404
    
    return jsonify({'success': True, 'messages': messages[chat_id]}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
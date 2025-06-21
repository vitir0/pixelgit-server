import os
import jwt
import uuid
import json
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# Конфигурация
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'pixelgit_secret_2025')

# Подключение к PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

# Создаем таблицы при первом запуске
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Удаляем старые таблицы если существуют
    cur.execute("DROP TABLE IF EXISTS messages, chats, users, encryption_keys;")
    
    # Создаем таблицы
    cur.execute("""
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        chats TEXT[]
    );
    """)
    
    cur.execute("""
    CREATE TABLE chats (
        id TEXT PRIMARY KEY,
        participants TEXT[] NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        last_message TEXT,
        last_message_time TIMESTAMPTZ
    );
    """)
    
    cur.execute("""
    CREATE TABLE messages (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    
    cur.execute("""
    CREATE TABLE encryption_keys (
        chat_id TEXT PRIMARY KEY,
        key TEXT NOT NULL
    );
    """)
    
    conn.commit()
    cur.close()
    conn.close()

# Инициализируем БД при старте
init_db()

# Вспомогательные функции для работы с БД
def execute_query(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(query, params)
    
    result = None
    if fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()
    
    if commit:
        conn.commit()
    
    cur.close()
    conn.close()
    return result

@app.route('/')
def index():
    return "PixelGit API is running on Render!"

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (username,),
        fetchone=True
    )
    
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
    
    existing_user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (username,),
        fetchone=True
    )
    
    if existing_user:
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    
    # Хешируем пароль
    hashed_password = generate_password_hash(password)
    user_id = str(uuid.uuid4())
    
    execute_query(
        "INSERT INTO users (id, username, password, chats) VALUES (%s, %s, %s, %s)",
        (user_id, username, hashed_password, []),
        commit=True
    )
    
    return jsonify({
        'success': True,
        'message': 'User registered successfully',
        'userId': user_id
    }), 201

@app.route('/users', methods=['GET'])
def get_users():
    users = execute_query("SELECT id, username FROM users", fetchall=True)
    return jsonify(users), 200

@app.route('/chats', methods=['POST'])
def create_chat():
    data = request.get_json()
    user1 = data.get('user1')
    user2 = data.get('user2')
    
    if not user1 or not user2:
        return jsonify({'success': False, 'message': 'Both users are required'}), 400
    
    # Проверяем существование пользователей
    user1_exists = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (user1,),
        fetchone=True
    )
    user2_exists = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (user2,),
        fetchone=True
    )
    
    if not user1_exists or not user2_exists:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    # Проверяем, существует ли уже чат
    existing_chat = execute_query(
        "SELECT id FROM chats WHERE participants @> ARRAY[%s, %s]",
        (user1, user2),
        fetchone=True
    )
    
    if existing_chat:
        return jsonify({
            'success': True,
            'message': 'Chat already exists',
            'chatId': existing_chat['id']
        }), 200
    
    # Создаем уникальный ID чата
    chat_id = str(uuid.uuid4())
    
    # Создаем чат
    execute_query(
        "INSERT INTO chats (id, participants, created_at) VALUES (%s, %s, %s)",
        (chat_id, [user1, user2], datetime.now(timezone.utc)),
        commit=True
    )
    
    # Добавляем чат пользователям
    execute_query(
        "UPDATE users SET chats = array_append(chats, %s) WHERE username = %s",
        (chat_id, user1),
        commit=True
    )
    execute_query(
        "UPDATE users SET chats = array_append(chats, %s) WHERE username = %s",
        (chat_id, user2),
        commit=True
    )
    
    return jsonify({
        'success': True,
        'message': 'Chat created successfully',
        'chatId': chat_id
    }), 201

@app.route('/chats/<username>', methods=['GET'])
def get_user_chats(username):
    user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (username,),
        fetchone=True
    )
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    chat_list = []
    for chat_id in user['chats']:
        chat = execute_query(
            "SELECT * FROM chats WHERE id = %s",
            (chat_id,),
            fetchone=True
        )
        
        if chat:
            participants = chat['participants']
            other_user = participants[0] if participants[1] == username else participants[1]
            
            chat_list.append({
                'id': chat_id,
                'with_user': other_user,
                'last_message': chat['last_message'],
                'last_message_time': chat['last_message_time'].isoformat() if chat['last_message_time'] else None
            })
    
    return jsonify({'success': True, 'chats': chat_list}), 200

@app.route('/chats/<chat_id>/key', methods=['GET', 'POST'])
def handle_encryption_key(chat_id):
    if request.method == 'GET':
        key = execute_query(
            "SELECT key FROM encryption_keys WHERE chat_id = %s",
            (chat_id,),
            fetchone=True
        )
        
        if key:
            return jsonify({'success': True, 'key': key['key']}), 200
        else:
            return jsonify({'success': False, 'message': 'Key not found'}), 404
    
    elif request.method == 'POST':
        data = request.get_json()
        key = data.get('key')
        
        if not key:
            return jsonify({'success': False, 'message': 'Key is required'}), 400
        
        # Обновляем или вставляем ключ
        execute_query(
            "INSERT INTO encryption_keys (chat_id, key) VALUES (%s, %s) "
            "ON CONFLICT (chat_id) DO UPDATE SET key = EXCLUDED.key",
            (chat_id, key),
            commit=True
        )
            
        return jsonify({'success': True, 'message': 'Encryption key saved'}), 200

@app.route('/messages', methods=['POST'])
def send_message():
    data = request.get_json()
    chat_id = data.get('chatId')
    sender = data.get('sender')
    text = data.get('text')
    
    if not chat_id or not sender or not text:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    chat = execute_query(
        "SELECT * FROM chats WHERE id = %s",
        (chat_id,),
        fetchone=True
    )
    
    if not chat:
        return jsonify({'success': False, 'message': 'Chat not found'}), 404
    
    if sender not in chat['participants']:
        return jsonify({'success': False, 'message': 'User not in chat'}), 403
    
    # Создаем сообщение
    message_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    
    execute_query(
        "INSERT INTO messages (id, chat_id, sender, text, timestamp) "
        "VALUES (%s, %s, %s, %s, %s)",
        (message_id, chat_id, sender, text, timestamp),
        commit=True
    )
    
    # Обновляем последнее сообщение в чате
    execute_query(
        "UPDATE chats SET last_message = %s, last_message_time = %s "
        "WHERE id = %s",
        ("🔒 Encrypted message", timestamp, chat_id),
        commit=True
    )
    
    return jsonify({
        'success': True,
        'message': 'Message sent successfully',
        'messageId': message_id
    }), 201

@app.route('/messages/<chat_id>', methods=['GET'])
def get_chat_messages(chat_id):
    messages = execute_query(
        "SELECT * FROM messages WHERE chat_id = %s ORDER BY timestamp",
        (chat_id,),
        fetchall=True
    )
    
    if not messages:
        return jsonify({'success': False, 'message': 'Chat not found'}), 404
    
    # Конвертируем datetime в строки
    for msg in messages:
        msg['timestamp'] = msg['timestamp'].isoformat()
    
    return jsonify({'success': True, 'messages': messages}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
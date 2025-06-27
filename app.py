import os
import jwt
import uuid
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
    return psycopg2.connect(DATABASE_URL, sslmode='require')

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
        chats TEXT[],
        avatar TEXT,
        email TEXT
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
        text TEXT,
        timestamp TIMESTAMPTZ DEFAULT NOW(),
        file_type TEXT,
        file_data TEXT
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
        'username': username,
        'avatar': user.get('avatar', '')
    }), 200

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email', '')
    avatar = data.get('avatar', 'https://api.dicebear.com/7.x/identicon/svg?seed=default&scale=80')
    
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
        "INSERT INTO users (id, username, password, chats, avatar, email) VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, username, hashed_password, [], avatar, email),
        commit=True
    )
    
    # Создаем JWT токен для нового пользователя
    payload = {
        'sub': username,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({
        'success': True,
        'message': 'User registered successfully',
        'token': token,
        'userId': user_id,
        'avatar': avatar
    }), 201

@app.route('/users', methods=['GET'])
def get_users():
    current_user = request.args.get('current')
    users = execute_query("SELECT id, username, avatar FROM users", fetchall=True)
    
    # Фильтруем текущего пользователя из списка
    filtered_users = [user for user in users if user['username'] != current_user]
    
    return jsonify(filtered_users), 200

# Новый эндпоинт для получения чатов пользователя
@app.route('/chats/<username>', methods=['GET'])
def get_user_chats(username):
    # Найти все чаты пользователя
    chats = execute_query(
        "SELECT * FROM chats WHERE %s = ANY(participants)",
        (username,),
        fetchall=True
    )
    
    if not chats:
        return jsonify({'success': True, 'chats': []}), 200

    enriched_chats = []
    for chat in chats:
        # Участники чата
        participants = chat['participants']
        # Найти собеседника (не текущий username)
        other_user = participants[0] if participants[1] == username else participants[1]
        
        # Получить аватар собеседника
        user_info = execute_query(
            "SELECT avatar FROM users WHERE username = %s",
            (other_user,),
            fetchone=True
        )
        avatar = user_info['avatar'] if user_info else ''
        
        enriched_chats.append({
            'id': chat['id'],
            'with_user': other_user,
            'last_message': chat['last_message'],
            'last_message_time': chat['last_message_time'],
            'avatar': avatar
        })
    
    return jsonify({'success': True, 'chats': enriched_chats}), 200

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
    file_type = data.get('file_type')
    file_data = data.get('file_data')
    
    if not chat_id or not sender or (not text and not file_data):
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
    
    # Проверка размера файла (4MB)
    if file_data and len(file_data) > 4 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'File size exceeds 4MB'}), 400
    
    # Создаем сообщение
    message_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    
    execute_query(
        "INSERT INTO messages (id, chat_id, sender, text, timestamp, file_type, file_data) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (message_id, chat_id, sender, text, timestamp, file_type, file_data),
        commit=True
    )
    
    # Обновляем последнее сообщение в чате
    last_msg = "📷 Photo" if file_type == 'image' else "🎬 Video" if file_type == 'video' else text
    execute_query(
        "UPDATE chats SET last_message = %s, last_message_time = %s "
        "WHERE id = %s",
        (last_msg, timestamp, chat_id),
        commit=True
    )
    
    # Возвращаем полную информацию о сообщении
    return jsonify({
        'success': True,
        'message': {
            'id': message_id,
            'chat_id': chat_id,
            'sender': sender,
            'text': text,
            'timestamp': timestamp.isoformat(),
            'file_type': file_type,
            'file_data': file_data
        }
    }), 201

@app.route('/messages/<chat_id>', methods=['GET'])
def get_chat_messages(chat_id):
    # Проверяем существование чата
    chat = execute_query(
        "SELECT * FROM chats WHERE id = %s",
        (chat_id,),
        fetchone=True
    )
    
    if not chat:
        return jsonify({'success': False, 'message': 'Chat not found'}), 404
    
    messages = execute_query(
        "SELECT * FROM messages WHERE chat_id = %s ORDER BY timestamp",
        (chat_id,),
        fetchall=True
    )
    
    # Возвращаем пустой массив если сообщений нет
    if not messages:
        return jsonify({'success': True, 'messages': []}), 200
    
    # Добавляем аватары отправителей
    for msg in messages:
        msg['timestamp'] = msg['timestamp'].isoformat()
        user = execute_query(
            "SELECT avatar FROM users WHERE username = %s",
            (msg['sender'],),
            fetchone=True
        )
        msg['avatar'] = user['avatar'] if user else ''
    
    return jsonify({'success': True, 'messages': messages}), 200

@app.route('/delete-message/<message_id>', methods=['DELETE'])
def delete_message(message_id):
    # Удаляем сообщение
    execute_query(
        "DELETE FROM messages WHERE id = %s",
        (message_id,),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Message deleted'}), 200

@app.route('/delete-chat/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    # Удаляем все связанные данные
    execute_query("DELETE FROM messages WHERE chat_id = %s", (chat_id,), commit=True)
    execute_query("DELETE FROM encryption_keys WHERE chat_id = %s", (chat_id,), commit=True)
    execute_query("DELETE FROM chats WHERE id = %s", (chat_id,), commit=True)
    
    # Удаляем chat_id из пользователей
    execute_query(
        "UPDATE users SET chats = array_remove(chats, %s)",
        (chat_id,),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Chat deleted'}), 200

@app.route('/update-username', methods=['POST'])
def update_username():
    data = request.get_json()
    current_username = data.get('currentUsername')
    new_username = data.get('newUsername')
    
    if not current_username or not new_username:
        return jsonify({'success': False, 'message': 'Both usernames are required'}), 400
    
    # Проверяем существует ли новый username
    existing_user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (new_username,),
        fetchone=True
    )
    
    if existing_user:
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    
    # Обновляем имя пользователя
    execute_query(
        "UPDATE users SET username = %s WHERE username = %s",
        (new_username, current_username),
        commit=True
    )
    
    # Обновляем во всех чатах
    execute_query(
        "UPDATE chats SET participants = array_replace(participants, %s, %s)",
        (current_username, new_username),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Username updated successfully'}), 200

@app.route('/update-password', methods=['POST'])
def update_password():
    data = request.get_json()
    username = data.get('username')
    current_password = data.get('currentPassword')
    new_password = data.get('newPassword')
    
    if not username or not current_password or not new_password:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400
    
    # Проверяем текущий пароль
    user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (username,),
        fetchone=True
    )
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    if not check_password_hash(user['password'], current_password):
        return jsonify({'success': False, 'message': 'Invalid current password'}), 401
    
    # Хешируем новый пароль
    hashed_password = generate_password_hash(new_password)
    
    # Обновляем пароль
    execute_query(
        "UPDATE users SET password = %s WHERE username = %s",
        (hashed_password, username),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Password updated successfully'}), 200

@app.route('/update-avatar', methods=['POST'])
def update_avatar():
    data = request.get_json()
    username = data.get('username')
    avatar = data.get('avatar')  # base64 encoded image
    
    if not username or not avatar:
        return jsonify({'success': False, 'message': 'Username and avatar are required'}), 400
    
    # Обновляем аватар
    execute_query(
        "UPDATE users SET avatar = %s WHERE username = %s",
        (avatar, username),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Avatar updated successfully'}), 200

@app.route('/delete-account', methods=['DELETE'])
def delete_account():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400
    
    # Находим пользователя по username
    user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (username,),
        fetchone=True
    )
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    if not check_password_hash(user['password'], password):
        return jsonify({'success': False, 'message': 'Invalid password'}), 401
    
    user_id = user['id']
    
    # Удаляем пользователя по ID
    execute_query(
        "DELETE FROM users WHERE id = %s",
        (user_id,),
        commit=True
    )
    
    # Удаляем связанные данные
    execute_query(
        "DELETE FROM chats WHERE %s = ANY(participants)",
        (username,),
        commit=True
    )
    
    return jsonify({'success': True, 'message': 'Account deleted successfully'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

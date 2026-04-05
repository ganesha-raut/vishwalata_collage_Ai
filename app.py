from flask import Flask, request, jsonify, render_template, send_from_directory, Response, stream_with_context, send_file, make_response, redirect, url_for, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import sqlite3
import os
import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
import secrets
import re
import time
import pandas as pd
from io import BytesIO
from werkzeug.utils import secure_filename
import bcrypt

from ai_models import get_ai_model, get_active_model_info, ACTIVE_MODEL


app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevents JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['UPLOAD_FOLDER'] = 'uploads/gallery'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

ALLOWED_ORIGINS = ["http://localhost:5000", "http://127.0.0.1:5000"]

CORS(app, resources={
    r"/api/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "X-API-Key"]
    }
})

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # Suppress socket.io handshake logs

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    manage_qs=False,
    engineio_logger=False,  # Disable engine.io logging
    logger=False  # Disable socket.io logging
)

API_KEY = secrets.token_urlsafe(32)
print(f"\n{'='*60}\nAPI KEY (Save this for frontend): {API_KEY}\n{'='*60}\n")

print(f"\n🤖 Using AI Model: {get_active_model_info()['active_model'].upper()} - {get_active_model_info()['model_name']}")

sessions = {}
SESSION_TIMEOUT = timedelta(minutes=30)
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS = 240
REQUIRED_INQUIRY_FIELDS = ['interested_course', 'name', 'qualification', 'contact']

# conect nd fecth db
def init_db():
    conn = sqlite3.connect('college_ai.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT NOT NULL,
        duration TEXT,
        eligibility TEXT,
        fees TEXT,
        key_subjects TEXT,
        admission_process TEXT,
        career_opportunities TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS campus_gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        tag TEXT,
        image_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        industry_name TEXT,
        location TEXT,
        website TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS students_placed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT NOT NULL,
        course_name TEXT,
        company_name TEXT,
        package TEXT,
        year INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        contact TEXT,
        qualification TEXT,
        percentage_probability REAL,
        interested_course TEXT,
        user_query TEXT,
        ai_summary TEXT,
        admission_probability TEXT,
        status TEXT DEFAULT 'pending',
        session_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admin_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    try:
        c.execute("SELECT * FROM admin_credentials WHERE id = 1")
        if not c.fetchone():
            default_email = "admin@vishwalta.edu.in"
            default_password = "Admin@123"  # Change this after first login!
            password_hash = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt())
            c.execute("INSERT INTO admin_credentials (email, password_hash) VALUES (?, ?)", 
                     (default_email, password_hash))
            print(f"\n{'='*60}\nDefault Admin Created:\nEmail: {default_email}\nPassword: {default_password}\nCHANGE THIS PASSWORD AFTER FIRST LOGIN!\n{'='*60}\n")
    except Exception as e:
        print(f"Admin initialization error: {e}")
    
    conn.commit()
    conn.close()

# wrkng on require_api_key
def require_api_key(f):
    @wraps(f)
    # wrkng on decorated_function
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.cookies.get('api_session_token')
        if api_key != API_KEY:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# admn rountes
def require_admin_login(f):
    @wraps(f)
    # wrkng on decorated_function
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# wrkng on hash_password
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

# wrkng on verify_password
def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash)
    except:
        return False

@app.before_request
# wrkng on before_request
def before_request():
    """Make session permanent for authenticated users"""
    session.permanent = True
    app.permanent_session_lifetime = timedelta(hours=24)

# conect nd fecth db
def get_db():
    conn = sqlite3.connect('college_ai.db')
    conn.row_factory = sqlite3.Row
    return conn

# wrkng on dict_from_row
def dict_from_row(row):
    return dict(zip(row.keys(), row)) if row else None


@app.route('/admin/login', methods=['GET', 'POST'])
# admn rountes
def admin_login():
    if 'admin_id' in session:
        print(f"Admin {session.get('admin_email')} already has valid session, redirecting to /admin")
        return redirect(url_for('admin'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('login.html', error='Email and password are required')
        
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id, email, password_hash, is_active FROM admin_credentials WHERE email = ?", (email,))
            admin = c.fetchone()
            conn.close()
            
            if admin and admin[3] and verify_password(password, admin[2]):
                session['admin_id'] = admin[0]
                session['admin_email'] = admin[1]
                session.permanent = True  # Make session persistent for 24 hours
                session.modified = True  # Tell Flask to save this session
                
                resp = make_response(redirect(url_for('admin')))
                resp.set_cookie(
                    'session',
                    value=session.sid if hasattr(session, 'sid') else '',
                    max_age=86400,  # 24 hours
                    httponly=True,
                    samesite='Lax'
                )
                
                # print(f"Admin {admin[1]} logged in")
                return resp
            else:
                return render_template('login.html', error='Invalid email or password')
        except Exception as e:
            print(f"Login error: {e}")
            return render_template('login.html', error='An error occurred. Please try again.')
    
    return render_template('login.html')


@app.route('/admin/logout', methods=['GET', 'POST'])
# admn rountes
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/')
# core cht mssg fn
def chat():
    resp = make_response(render_template('chat.html', api_key=API_KEY))
    resp.set_cookie('api_session_token', API_KEY, httponly=True, samesite='Strict')
    return resp


@app.route('/admin')
@require_admin_login
# admn rountes
def admin():
    session.permanent = True
    session.modified = True
    
    resp = make_response(render_template('admin.html', api_key=API_KEY, admin_email=session.get('admin_email')))
    resp.set_cookie('api_session_token', API_KEY, httponly=True, samesite='Strict')
    
    resp.set_cookie(
        'session',
        value=request.cookies.get('session', ''),
        max_age=86400,  # 24 hours
        httponly=True,
        samesite='Lax',
        path='/'
    )
    
    return resp


@app.route('/uploads/gallery/<filename>')
# wrkng on serve_gallery_image
def serve_gallery_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/<path:filename>')
# wrkng on serve_static
def serve_static(filename):
    return send_from_directory('.', filename)


@app.route('/api/admin/profile', methods=['GET'])
@require_admin_login
# admn rountes
def get_admin_profile():
    """Get current admin profile information"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, email, created_at, updated_at FROM admin_credentials WHERE id = ?", (session.get('admin_id'),))
        admin = c.fetchone()
        conn.close()
        
        if admin:
            return jsonify({
                'id': admin[0],
                'email': admin[1],
                'created_at': admin[2],
                'updated_at': admin[3]
            })
        return jsonify({'error': 'Admin not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/change-email', methods=['POST'])
@require_admin_login
# admn rountes
def change_admin_email():
    """Change admin email address"""
    try:
        data = request.json
        new_email = data.get('new_email', '').strip()
        password = data.get('password', '')
        
        if not new_email or not password:
            return jsonify({'error': 'New email and password are required'}), 400
        
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
            return jsonify({'error': 'Invalid email format'}), 400
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT password_hash FROM admin_credentials WHERE id = ?", (session.get('admin_id'),))
        result = c.fetchone()
        
        if not result or not verify_password(password, result[0]):
            conn.close()
            return jsonify({'error': 'Incorrect password'}), 401
        
        c.execute("SELECT id FROM admin_credentials WHERE email = ? AND id != ?", (new_email, session.get('admin_id')))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Email already in use'}), 400
        
        c.execute("UPDATE admin_credentials SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", 
                 (new_email, session.get('admin_id')))
        conn.commit()
        conn.close()
        
        session['admin_email'] = new_email
        
        return jsonify({'message': 'Email changed successfully', 'new_email': new_email})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/change-password', methods=['POST'])
@require_admin_login
# admn rountes
def change_admin_password():
    """Change admin password"""
    try:
        data = request.json
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        if not old_password or not new_password or not confirm_password:
            return jsonify({'error': 'All fields are required'}), 400
        
        if new_password != confirm_password:
            return jsonify({'error': 'New passwords do not match'}), 400
        
        if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isalpha() for c in new_password):
            return jsonify({'error': 'Password must be at least 8 characters with numbers and letters'}), 400
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT password_hash FROM admin_credentials WHERE id = ?", (session.get('admin_id'),))
        result = c.fetchone()
        
        if not result or not verify_password(old_password, result[0]):
            conn.close()
            return jsonify({'error': 'Incorrect current password'}), 401
        
        new_password_hash = hash_password(new_password)
        c.execute("UPDATE admin_credentials SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", 
                 (new_password_hash, session.get('admin_id')))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Password changed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/session/create', methods=['POST'])
@require_api_key
# mang user seesion
def create_session():
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        'created_at': datetime.now(),
        'data': {},
        'messages': [],
        'inquiry_created': False,
        'last_requested_field': None
    }
    return jsonify({'session_id': session_id})

@app.route('/api/session/<session_id>', methods=['GET'])
@require_api_key
# mang user seesion
def get_session(session_id):
    if session_id in sessions:
        if datetime.now() - sessions[session_id]['created_at'] > SESSION_TIMEOUT:
            del sessions[session_id]
            return jsonify({'error': 'Session expired'}), 404
        return jsonify(sessions[session_id])
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/chat', methods=['POST'])
@require_api_key
# core cht mssg fn
def chat_ai():
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id')
    stream_mode = data.get('stream', True)  # Enable streaming by default
    preferred_language = data.get('preferred_language', 'auto')
    
    if not session_id or session_id not in sessions:
        return jsonify({'error': 'Invalid session'}), 400
    
    session = sessions[session_id]
    session['messages'].append({'role': 'user', 'content': user_message})
    
    try:
        conn = get_db()
        courses = conn.execute('SELECT * FROM courses').fetchall()
        gallery = conn.execute('SELECT * FROM campus_gallery').fetchall()
        companies = conn.execute('SELECT * FROM companies').fetchall()
        students_placed = conn.execute('SELECT * FROM students_placed ORDER BY year DESC').fetchall()
        conn.close()
        
        context = build_ai_context(courses, gallery, companies, students_placed, session['data'], preferred_language, session['messages'])
        
        ai_model = get_ai_model()
        
        full_prompt = f"""{context}

User: "{user_message}"
Respond in markdown only for the visible reply. Keep it punchy, persuasive, and playful. Do not ask any follow-up question yourself because the application will append the next question. Put structured data only in the final JSON block."""
        
        full_text = ""
        for token in ai_model.generate_stream(full_prompt, system_instruction=""):
            full_text += token
        
        ai_response = finalize_ai_response(
            session_id,
            user_message,
            preferred_language,
            parse_ai_response(full_text),
            courses
        )
        
        ai_response['stream_enabled'] = stream_mode
        
        return jsonify(ai_response)
        
    except Exception as e:
        print(f"Chat API Error: {str(e)}")  # Log the error
        return jsonify({
            'error': str(e), 
            'response': 'Sorry, I encountered an error. Please try again.',
            'extracted_data': {},
            'ready_to_submit': False
        }), 500

@app.route('/api/chat/stream', methods=['POST'])
@require_api_key
# core cht mssg fn
def chat_ai_stream():
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id')
    preferred_language = data.get('preferred_language', 'auto')
    
    if not session_id:
        return jsonify({'error': 'Session ID required'}), 400
    
    if session_id not in sessions:
        print(f'🔄 Recreating lost session: {session_id}')
        sessions[session_id] = {
            'created_at': datetime.now(),
            'data': {},
            'messages': [],
            'inquiry_created': False,
            'last_requested_field': None
        }
    
    # run ai gernate msg
    def generate():
        try:
            session = sessions[session_id]
            session['messages'].append({'role': 'user', 'content': user_message})
            
            conn = get_db()
            courses = conn.execute('SELECT * FROM courses').fetchall()
            gallery = conn.execute('SELECT * FROM campus_gallery').fetchall()
            companies = conn.execute('SELECT * FROM companies').fetchall()
            students_placed = conn.execute('SELECT * FROM students_placed ORDER BY year DESC').fetchall()
            conn.close()
            
            context = build_ai_context(courses, gallery, companies, students_placed, session['data'], preferred_language, session['messages'])
            
            ai_model = get_ai_model()
            
            full_prompt = f"""{context}

User: "{user_message}"
Respond in markdown only for the visible reply. Keep it punchy, persuasive, and playful. Do not ask any follow-up question yourself because the application will append the next question. Put structured data only in the final JSON block."""
            
            full_text = ""
            in_json_block = False
            json_depth = 0
            
            for token in ai_model.generate_stream(full_prompt, system_instruction=""):
                full_text += token
                
                if '```json' in token:
                    in_json_block = True
                    
                if not in_json_block:
                    yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
                    
                if in_json_block and '```' in token and token.strip() != '```json':
                    pass
            
            ai_response = finalize_ai_response(
                session_id,
                user_message,
                preferred_language,
                parse_ai_response(full_text),
                courses
            )
            
            yield f"data: {json.dumps({'done': True, 'metadata': ai_response})}\n\n"
            
        except Exception as e:
            print(f"Streaming Error: {str(e)}")
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@socketio.on('connect')
# wrkng on socket_connect
def socket_connect(auth=None):
    """Allow websocket connection only when secure API cookie is present."""
    try:
        api_key = request.cookies.get('api_session_token') or (auth or {}).get('apiKey')
        if api_key != API_KEY:
            return False  # Reject connection if API key invalid
        emit('connected', {'ok': True})
        return True  # Accept connection
    except Exception as e:
        print(f"Socket connection setup error: {e}")
        return False


@socketio.on('chat_message')
# core cht mssg fn
def socket_chat_message(data):
    """Realtime chat streaming over websocket for faster frontend rendering."""
    try:
        data = data or {}
        user_message = (data.get('message') or '').strip()
        session_id = data.get('session_id')
        preferred_language = data.get('preferred_language', 'auto')

        if not user_message:
            try:
                emit('chat_error', {'error': 'Message is required', 'done': True})
            except:
                pass
            return

        if not session_id:
            try:
                emit('chat_error', {'error': 'Session ID required', 'done': True})
            except:
                pass
            return
        
        if session_id not in sessions:
            print(f'🔄 Recreating lost socket session: {session_id}')
            sessions[session_id] = {
                'created_at': datetime.now(),
                'data': {},
                'messages': [],
                'inquiry_created': False,
                'last_requested_field': None,
                'pending_query': None
            }

        session = sessions[session_id]
        if 'pending_query' not in session:
            session['pending_query'] = None
        
        is_logged_in = session['data'].get('name') and session['data'].get('contact') and session['data'].get('qualification')
        
        if not is_logged_in:
            user_input = user_message.strip()
            
            parts = [p.strip() for p in re.split(r'[,;]', user_input) if p.strip()]
            
            extracted_name = None
            extracted_mobile = None
            extracted_qual = None
            
            if len(parts) >= 3:
                extracted_name = parts[0]
                extracted_mobile = re.sub(r'\D', '', parts[1])[-10:] if parts[1] else None  # Extract 10 digits
                extracted_qual = parts[2]
                
                if extracted_mobile and len(extracted_mobile) == 10:
                    session['data']['name'] = extracted_name
                    session['data']['contact'] = extracted_mobile
                    session['data']['qualification'] = extracted_qual
                    
                    if session.get('pending_query'):
                        user_message = session['pending_query']
                        session['pending_query'] = None  # Clear it
                        print(f"🔄 Restoring pending query: {user_message}")
                    
                    session['messages'].append({'role': 'user', 'content': user_message})
                    is_logged_in = True
                else:
                    session['pending_query'] = user_message  # Store it just in case!
                    error_prompt = """❌ Login error! Mobile number must be 10 digits.

Please send like this:
name, mobile number, qualification"""
                    try:
                        emit('chat_token', {'token': error_prompt, 'done': False, 'session_id': session_id})
                        emit('chat_done', {
                            'done': True,
                            'metadata': {
                                'extracted_data': session['data'],
                                'follow_up_suggestions': [],
                                'ready_to_submit': False
                            },
                            'session_id': session_id
                        })
                    except Exception as e:
                        print(f"Error: {e}")
                    return
            else:
                session['pending_query'] = user_message
                
                error_prompt = """❌ Occur login error! Login first:

1️⃣ Name
2️⃣ Mobile Number
3️⃣ Qualification
"""
                try:
                    emit('chat_token', {'token': error_prompt, 'done': False, 'session_id': session_id})
                    emit('chat_done', {
                        'done': True,
                        'metadata': {
                            'extracted_data': session['data'],
                            'follow_up_suggestions': [],
                            'ready_to_submit': False
                        },
                        'session_id': session_id
                    })
                except Exception as e:
                    print(f"Error: {e}")
                return
        else:
            session['messages'].append({'role': 'user', 'content': user_message})

        conn = get_db()
        courses = conn.execute('SELECT * FROM courses').fetchall()
        gallery = conn.execute('SELECT * FROM campus_gallery').fetchall()
        companies = conn.execute('SELECT * FROM companies').fetchall()
        students_placed = conn.execute('SELECT * FROM students_placed ORDER BY year DESC').fetchall()
        conn.close()

        context = build_ai_context(courses, gallery, companies, students_placed, session['data'], preferred_language, session['messages'])

        ai_model = get_ai_model()
        full_prompt = f"""{context}

User: \"{user_message}\"
Respond in markdown only for the visible reply. Keep it punchy, persuasive, and playful. Do not ask any follow-up question yourself because the application will append the next question. Put structured data only in the final JSON block."""

        full_text = ""
        in_json_block = False

        for token in ai_model.generate_stream(full_prompt, system_instruction=""):
            full_text += token

            if '```json' in token:
                in_json_block = True

            if not in_json_block and token:
                emit('chat_token', {'token': token, 'done': False, 'session_id': session_id})

        ai_response = finalize_ai_response(
            session_id,
            user_message,
            preferred_language,
            parse_ai_response(full_text),
            courses
        )

        emit('chat_done', {'done': True, 'metadata': ai_response, 'session_id': session_id})

    except Exception as e:
        print(f"WebSocket Chat Error: {str(e)}")
        emit('chat_error', {
            'error': str(e),
            'response': 'Sorry, I encountered an error. Please try again.',
            'done': True
        })

# wrkng on format_conversation_history
def format_conversation_history(conversation_history):
    """Format recent user and assistant messages for prompt memory."""
    if not conversation_history:
        return ""

    history_source = conversation_history[:-1] if conversation_history[-1].get('role') == 'user' else conversation_history
    if not history_source:
        return ""

    recent_history = history_source[-MAX_HISTORY_MESSAGES:]
    history_lines = ["\n\n## 📜 CONVERSATION HISTORY (Recent User + AI Messages):"]

    for index, msg in enumerate(recent_history, start=1):
        role = "User" if msg.get('role') == 'user' else "AI"
        content = (msg.get('content') or '').replace('\n', ' ').strip()
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS].rstrip() + '...'
        history_lines.append(f"{index}. {role}: {content}")

    history_lines.append("\n⚠️ USE THIS HISTORY TO:")
    history_lines.append("- Remember the user's earlier questions, preferences, and personal details already shared")
    history_lines.append("- Remember your own previous answers so you do not repeat the same pitch again")
    history_lines.append("- Continue the flow naturally as if this is one ongoing chat")
    history_lines.append("- If the user refers to 'that', 'it', or 'same one', resolve it from the recent conversation")
    return "\n".join(history_lines)


# wrkng on build_ai_context
def build_ai_context(courses, gallery, companies, students_placed, user_data, preferred_language='auto', conversation_history=[]):
    
    # ftech dta function
    def get_course_category(course_name):
        """Categorize course by name pattern"""
        name_lower = course_name.lower()
        
        if any(x in name_lower for x in ['bca', 'b.tech', 'cse', 'it', 'computer', 'tech', 'engineering', 'information']):
            return 'tech'
        elif any(x in name_lower for x in ['bcom', 'b.com', 'commerce', 'bba', 'accounting', 'finance']):
            return 'commerce'
        elif any(x in name_lower for x in ['ba', 'b.a', 'arts', 'humanities', 'social']):
            return 'arts'
        elif any(x in name_lower for x in ['b.sc', 'science', 'physics', 'chemistry', 'biology']):
            return 'science'
        else:
            return 'other'
    
    interested_course = user_data.get('interested_course', '').lower()
    
    if interested_course:
        focused_course = None
        
        for c in courses:
            course_dict = dict_from_row(c)
            if course_dict['course_name'].lower() == interested_course:
                focused_course = course_dict
                break
        
        if focused_course:
            courses_info = f"🎯 TARGET COURSE: {focused_course['course_name']}\n"
            courses_info += f"- Duration: {focused_course.get('duration') or 'Contact Administration'}\n"
            courses_info += f"- Fees: {focused_course.get('fees') or 'Contact Administration for Fee Structure'}\n"
            courses_info += f"- Eligibility: {focused_course.get('eligibility') or 'Contact Administration'}\n"
            courses_info += f"- Subjects: {focused_course.get('key_subjects') or 'N/A'}\n"
            
            course_placements = [dict_from_row(sp) for sp in students_placed if dict_from_row(sp).get('course_name', '').lower() == focused_course['course_name'].lower()]
            if course_placements:
                placement_str = ", ".join([f"{p['student_name']} (Placed in {p['company_name']}, Package: {p.get('package', 'N/A')}, Year: {p.get('year', '')})" for p in course_placements[:5]])
                courses_info += f"- Specific Course Placements: {placement_str}\n"

            courses_info += "\n🚨 AGGRESSIVE RULE: The user has selected this TARGET COURSE. You MUST immediately reply with the COMPLETE structured details (Fees, Duration, Eligibility, Placements) using bullet points!"
        else:
            courses_list = []
            full_forms = {'bca': 'Bachelor of Computer Applications', 'bcs': 'Bachelor of Computer Science', 'bsc': 'Bachelor of Science', 'bba': 'Bachelor of Business Administration', 'bcom': 'Bachelor of Commerce', 'ba': 'Bachelor of Arts'}
            for c in courses:
                c_dict = dict_from_row(c)
                c_name = c_dict['course_name']
                full_name = full_forms.get(c_name.lower(), c_name)
                courses_list.append(f"- **{c_name} ({full_name})**: Focuses on {c_dict.get('key_subjects', 'core professional topics')}.")
            courses_info = "Available Courses:\n" + "\n".join(courses_list)
    else:
        courses_list = []
        full_forms = {'bca': 'Bachelor of Computer Applications', 'bcs': 'Bachelor of Computer Science', 'bsc': 'Bachelor of Science', 'bba': 'Bachelor of Business Administration', 'bcom': 'Bachelor of Commerce', 'ba': 'Bachelor of Arts'}
        for c in courses:
            c_dict = dict_from_row(c)
            c_name = c_dict['course_name']
            full_name = full_forms.get(c_name.lower(), c_name)
            courses_list.append(f"- **{c_name} ({full_name})**: Focuses on {c_dict.get('key_subjects', 'core professional topics')}.")
        courses_info = "Available Courses:\n" + "\n".join(courses_list)

    companies_list = [dict_from_row(c)['company_name'] for c in companies[:10]] if companies else []
    companies_info = ", ".join(companies_list)
    
    placement_info = f"Over {len(students_placed)} students placed recently." if students_placed else "Contact us for placement info."

    gallery_list = []
    for g in gallery:
        g_dict = dict_from_row(g) if hasattr(g, 'keys') else g
        gallery_list.append({
            'title': g_dict['title'],
            'tag': g_dict.get('tag', ''),
            'image_path': g_dict['image_path']
        })
    
    gallery_count = len(gallery)
    gallery_tags = list(set([g.get('tag', '').lower() for g in gallery_list if g.get('tag')]))
    
    language_instructions = {
        'marathi_english': """🚨 DEFAULT LANGUAGE RULE: User selected MARATHI + ENGLISH mixed mode.
⚠️ Reply in a natural Marathi + English mixed style by default. Keep the tone conversational.
Example: "Amchya college madhe swagat ahe! Khaali dilelya list madhun tumhala kontya field madhe interest ahe?""",
        'english': """🚨 CRITICAL LANGUAGE RULE: User selected ENGLISH from dropdown.
⚠️ RESPOND **ONLY IN ENGLISH** - No matter what language user types in!
⚠️ DO NOT use any Marathi/Hindi words - 100% PURE ENGLISH ONLY
Example: "Welcome to our college! From the list below, which field are you interested in?""",
        'marathi': """🚨 अतिशय महत्त्वाचं: User ने मराठी language निवडली आहे.
⚠️ फक्त मराठीतच उत्तर द्या - User कोणत्याही language मध्ये लिहिलं तरी
Example: "आमच्या कॉलेजमध्ये स्वागत आहे! खाली दिलेल्या लिस्टमधून तुम्हाला कोणत्या क्षेत्रात रस आहे?""",
        'hindi': """🚨 बहुत जरूरी: User ने हिंदी language select की है.
⚠️ सिर्फ हिंदी में जवाब दें - User चाहे किसी भी language में लिखे
Example: "हमारे कॉलेज में स्वागत है! कृपया बताएं कि आपकी रुचि किस क्षेत्र में है?""",
        'auto': 'AUTO MODE: Detect user language automatically and respond in SAME language (Marathi/English/Hindi/Mixed). Match user\'s language choice.'
    }
    
    lang_instruction = language_instructions.get(preferred_language, language_instructions['auto'])
    
    history_text = format_conversation_history(conversation_history)
    
    chat_mode = "onboarding"
    is_first_user = not (user_data.get('name') and user_data.get('contact'))
    
    if user_data.get('name') and user_data.get('contact'):
        if not user_data.get('qualification'):
            chat_mode = "collect_qualification"
        elif not user_data.get('interested_course'):
            chat_mode = "interest_discovery"
        else:
            chat_mode = "course_guidance"
    
    context = f"""You are Vishwalata College's AI Assistant.

Chat Mode: {chat_mode}
{history_text}

Language Mode: {lang_instruction}

COLLEGE DB:
{courses_info}
Placements: {placement_info} | Companies: {companies_info}
Gallery: {json.dumps(gallery_list)}

USER DATA:
Name: {user_data.get('name', 'None')} | Contact: {user_data.get('contact', 'None')}
Qualification: {user_data.get('qualification', 'None')} | Interest: {user_data.get('interested_course', 'None')}

CRITICAL RULES:
1. DO NOT GUESS OR FORCE A COURSE! If the user simply asks "what courses are available", ONLY give them a neat bulleted list of Available Courses and ask what area they are interested in (Tech, Business, Science, etc...). DO NOT hallucinate descriptions. Use the exact text provided in the COLLEGE DB.
2. IF the user mentions a general stream like "computer", "business", or "science", DO NOT forcefully assign a specific course (like BCA) to `extracted_data.interested_course`! Instead, list ALL courses related to their stream perfectly exactly from the DB and ask them to pick EXACTLY which one they want.
3. DETAILED COURSE INFO: If the user specifically asks about ONE course (like "Tell me about BCA" or "BCA chi information dya"), ALWAYS reply with a beautifully structured format:
   **[Course Name]**
   - **Fees:** 
   - **Duration:** 
   - **Eligibility:** 
   - **Top Recruiters:** (Mention companies from DB)
   - **Our Student Placements:** (ONLY IF 'Specific Course Placements' are provided in python variables above, mention them. Example: "Amche student Ganesh yanch placement...". IF NO PLACEMENTS DATA IS PROVIDED, DO NOT USE PLACEHOLDERS LIKE [Name] or [Company]! Just say 'Contact administration for latest placements'.)
4. DO NOT write long essays. NEITHER ASK ANY QUESTIONS NOR END WITH A QUESTION MARK! The system will automatically append the next conversational question for you.
5. IMAGES: If user asks for campus/library/etc, use `show_image` in JSON. You MUST use the EXACT `image_path` provided in the Gallery list. Do NOT invent image paths or titles.
6. IF the user is asking from a template or prompt directly right after giving details, GREET THEM by Name, use the above placement style to show off their requested course, and seamlessly continue!
7. NEVER ask for Name, Mobile, Qualification, or Interest if already present in USER DATA.

STRICT OUTPUT FORMAT:
Return normal markdown response, followed by this EXACT JSON block:

```json
{{
  "show_image": null,
  "extracted_data": {{
    "name": null,
    "contact": null,
    "qualification": null,
    "interested_course": null
  }},
  "student_analysis": {{
    "best_fit_courses": []
  }},
  "ready_to_submit": false
}}
```"""

    return context




# pars txt to json n data
def parse_ai_response(text):
    try:
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)

        if json_match:
            clean_text = text[:json_match.start()].strip()
        else:
            raw_json_match = re.search(r'\n*\{\s*["\'](?:show_image|extracted_data)["\']', text, re.DOTALL)
            if raw_json_match:
                clean_text = text[:raw_json_match.start()].strip()
            else:
                clean_text = text.strip()

        meta_phrases = [
            'so adjusting the response', 'since the user', 'my goal is',
            'according to the rules', 'yes, that makes sense', 'also, ensure',
            'and the json', 'let me check', 'i need to', 'i will now'
        ]
        parts = re.split(r'\n\s*\n', clean_text)
        clean_blocks = []
        for p in parts:
            pl = p.lower().strip()
            if (any(m in pl for m in meta_phrases)
                    or pl.startswith('okay')
                    or pl.startswith('let me')
                    or pl.startswith('hi when the user')
                    or pl.startswith('and the json')):
                continue
            clean_blocks.append(p)

        final_text = '\n\n'.join(clean_blocks).strip() if clean_blocks else clean_text

        result = {
            'response': final_text,
            'extracted_data': {},
            'ready_to_submit': False,
            'follow_up_suggestions': []
        }

        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if parsed.get('show_image'):
                    result['show_image'] = parsed['show_image']
                if parsed.get('extracted_data'):
                    result['extracted_data'] = parsed['extracted_data']
                if parsed.get('ready_to_submit'):
                    result['ready_to_submit'] = parsed['ready_to_submit']
                
                if parsed.get('student_analysis'):
                    analysis = parsed['student_analysis']
                    suggestions = []
                    
                    if analysis.get('best_fit_courses') and isinstance(analysis['best_fit_courses'], list):
                        suggestions.extend(analysis['best_fit_courses'][:3])  # Max 3 course suggestions
                    
                    result['follow_up_suggestions'] = suggestions if suggestions else []
                    
            except Exception as inner_e:
                print(f"⚠️ Failed to parse JSON block: {inner_e}")

        return result

    except Exception as e:
        print(f"❌ Parse error: {e}")
        return {
            'response': text,
            'extracted_data': {},
            'ready_to_submit': False,
            'follow_up_suggestions': []
        }


# wrkng on normalize_whitespace
def normalize_whitespace(value):
    return re.sub(r'\s+', ' ', (value or '')).strip()


# wrkng on sanitize_name
def sanitize_name(value):
    value = normalize_whitespace(value)
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z\s'.-]{1,49}", value):
        return None
    lowered = value.lower()
    if lowered in {'hi', 'hello', 'hey', 'ok', 'okay', 'yes', 'no', 'plain', 'account'}:
        return None
    return value.title()


# wrkng on sanitize_contact
def sanitize_contact(value):
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in '6789':
        return digits
    return None


# wrkng on sanitize_email
def sanitize_email(value):
    value = normalize_whitespace(value).lower()
    if re.fullmatch(r'[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', value):
        return value
    return None


# wrkng on sanitize_qualification
def sanitize_qualification(value):
    value = normalize_whitespace(value)
    lowered = value.lower()
    keywords = ['12th', 'hsc', 'commerce', 'science', 'arts', 'diploma', 'graduate', 'graduation', 'bcom', 'bca', 'bba', 'mcom', 'mba']
    if any(keyword in lowered for keyword in keywords):
        return value
    return None


# wrkng on detect_course_interest
def detect_course_interest(message, courses):
    lowered = normalize_whitespace(message).lower()
    aliases = {
        'bcom': 'BCom',
        'b.com': 'BCom',
        'bca': 'BCA',
        'bba': 'BBA',
        'bsc': 'BSc',
        'b.sc': 'BSc',
        'mba': 'MBA',
        'mcom': 'MCom'
    }

    for alias, canonical in aliases.items():
        if alias in lowered:
            return canonical

    for course in courses or []:
        course_name = dict_from_row(course).get('course_name', '')
        if course_name and course_name.lower() in lowered:
            return course_name

    return None


# wrkng on extract_name_from_message
def extract_name_from_message(message, last_requested_field=None):
    cleaned = normalize_whitespace(message)
    patterns = [
        r"(?:my name is|i am|i'm|this is)\s+([A-Za-z][A-Za-z\s'.-]{1,49})",
        r"(?:माझं नाव|माझे नाव|maza naav|maze nav)\s+([A-Za-z][A-Za-z\s'.-]{1,49})"
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return sanitize_name(match.group(1))

    if last_requested_field == 'name':
        return sanitize_name(cleaned)
    return None


# wrkng on extract_qualification_from_message
def extract_qualification_from_message(message, last_requested_field=None):
    cleaned = normalize_whitespace(message)
    qualification = sanitize_qualification(cleaned)
    if qualification:
        return qualification
    if last_requested_field == 'qualification':
        return sanitize_qualification(cleaned)
    return None


# wrkng on extract_user_details
def extract_user_details(message, session_data, courses, last_requested_field=None):
    extracted = {}
    validation_errors = {}
    cleaned = normalize_whitespace(message)

    email_match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', cleaned)
    if email_match:
        email = sanitize_email(email_match.group(0))
        if email:
            extracted['email'] = email

    course = detect_course_interest(cleaned, courses)
    if course:
        extracted['interested_course'] = course

    name = extract_name_from_message(cleaned, last_requested_field)
    if name:
        extracted['name'] = name

    qualification = extract_qualification_from_message(cleaned, last_requested_field)
    if qualification:
        extracted['qualification'] = qualification

    contact = sanitize_contact(cleaned)
    if contact:
        extracted['contact'] = contact
    elif last_requested_field == 'contact' and re.search(r'\d', cleaned):
        validation_errors['contact'] = 'invalid_contact'

    if last_requested_field == 'qualification' and 'qualification' not in extracted:
        low = cleaned.lower()
        if low not in {'yes', 'no', 'ok', 'okay', 'ho', 'nahi'}:
            validation_errors['qualification'] = 'invalid_qualification'

    if last_requested_field == 'name' and 'name' not in extracted:
        low = cleaned.lower()
        if low not in {'yes', 'no', 'ok', 'okay', 'ho', 'nahi'}:
            validation_errors['name'] = 'invalid_name'

    return extracted, validation_errors


# wrkng on sanitize_ai_extracted_data
def sanitize_ai_extracted_data(ai_extracted, courses):
    sanitized = {}
    if not isinstance(ai_extracted, dict):
        return sanitized

    if ai_extracted.get('name'):
        name = sanitize_name(ai_extracted.get('name'))
        if name:
            sanitized['name'] = name

    if ai_extracted.get('contact'):
        contact = sanitize_contact(ai_extracted.get('contact'))
        if contact:
            sanitized['contact'] = contact

    if ai_extracted.get('email'):
        email = sanitize_email(ai_extracted.get('email'))
        if email:
            sanitized['email'] = email

    if ai_extracted.get('qualification'):
        qualification = sanitize_qualification(ai_extracted.get('qualification'))
        if qualification:
            sanitized['qualification'] = qualification

    if ai_extracted.get('interested_course'):
        course = detect_course_interest(ai_extracted.get('interested_course'), courses)
        if course:
            sanitized['interested_course'] = course

    return sanitized


# wrkng on strip_follow_up_question
def strip_follow_up_question(response_text):
    response_text = re.sub(r'<div class="highlight-question">.*?</div>', '', response_text or '', flags=re.DOTALL)
    return response_text.strip()


# ftech dta function
def get_missing_fields(data):
    return [field for field in REQUIRED_INQUIRY_FIELDS if not data.get(field)]


# ftech dta function
def get_language_mode(preferred_language):
    return preferred_language if preferred_language in {'english', 'marathi', 'hindi', 'marathi_english'} else 'marathi_english'


# wrkng on build_follow_up_question
def build_follow_up_question(field_name, preferred_language, session_data, validation_errors=None):
    language_mode = get_language_mode(preferred_language)
    validation_errors = validation_errors or {}
    first_name = (session_data.get('name') or '').split(' ')[0] if session_data.get('name') else ''
    prefix = f"{first_name}, " if first_name else ''

    questions = {
        'marathi_english': {
            'interested_course': f"{prefix}tumche career goals aani aavad (interest) kay aahe? tyasar mi tumhala changla course suggest karen.",
            'name': "Mast. Tumcha full name kay aahe?",
            'qualification': f"{prefix}tumchi qualification kay aahe? `12th Commerce`, `12th Science`, `Arts`, `Diploma` ki `Graduation`?",
            'contact': f"Perfect. {prefix}tumcha valid 10-digit contact number share kara, admissions team tumhala connect hoil.",
            'invalid_contact': f"{prefix}number thoda incorrect disatoy. Please valid 10-digit mobile number share kara.",
            'invalid_qualification': f"{prefix}qualification thodi clearly sanga na, jase `12th Commerce`, `12th Science`, `Arts`, `Diploma` ki `Graduation`.",
            'invalid_name': "Tumcha full name thoda clearly share kara na."
        },
        'marathi': {
            'interested_course': f"{prefix}तुमचे करिअर गोल्स आणि आवड काय आहे? त्यानुसार मी तुम्हाला योग्य कोर्स सुचवेन.",
            'name': "छान. तुमचं पूर्ण नाव काय आहे?",
            'qualification': f"{prefix}तुमची शैक्षणिक पात्रता काय आहे? `12th Commerce`, `12th Science`, `Arts`, `Diploma` की `Graduation`?",
            'contact': f"Perfect. {prefix}तुमचा वैध 10 अंकी संपर्क क्रमांक शेअर करा.",
            'invalid_contact': f"{prefix}तुमचा नंबर चुकीचा दिसतोय. कृपया वैध 10 अंकी मोबाईल नंबर पाठवा.",
            'invalid_qualification': f"{prefix}तुमची शैक्षणिक पात्रता स्पष्ट सांगा, जसे `12th Commerce`, `12th Science`, `Arts`, `Diploma` की `Graduation`.",
            'invalid_name': "कृपया तुमचं पूर्ण नाव स्पष्टपणे पाठवा."
        },
        'english': {
            'interested_course': f"{prefix}what are your career goals and interests? I can suggest the best course for you.",
            'name': "Great. What is your full name?",
            'qualification': f"{prefix}what is your current qualification? `12th Commerce`, `12th Science`, `Arts`, `Diploma`, or `Graduation`?",
            'contact': f"Perfect. {prefix}please share your valid 10-digit contact number so the admissions team can reach you.",
            'invalid_contact': f"{prefix}that number looks invalid. Please share a valid 10-digit mobile number.",
            'invalid_qualification': f"{prefix}please mention your qualification clearly, for example `12th Commerce`, `12th Science`, `Arts`, `Diploma`, or `Graduation`.",
            'invalid_name': "Please share your full name clearly."
        },
        'hindi': {
            'interested_course': f"{prefix}आपके करियर गोल्स और दिलचस्पी क्या है? उसके अनुसार मैं आपको सही कोर्स बताऊँगा.",
            'name': "बहुत बढ़िया. आपका पूरा नाम क्या है?",
            'qualification': f"{prefix}आपकी qualification क्या है? `12th Commerce`, `12th Science`, `Arts`, `Diploma` या `Graduation`?",
            'contact': f"Perfect. {prefix}कृपया अपना valid 10-digit contact number share करें.",
            'invalid_contact': f"{prefix}यह number सही नहीं लग रहा. कृपया valid 10-digit mobile number भेजें.",
            'invalid_qualification': f"{prefix}अपनी qualification थोड़ा clearly बताइए, जैसे `12th Commerce`, `12th Science`, `Arts`, `Diploma` या `Graduation`.",
            'invalid_name': "कृपया अपना पूरा नाम साफ़-साफ़ बताइए."
        }
    }

    bundle = questions[language_mode]
    if validation_errors.get('contact'):
        return bundle['invalid_contact']
    if validation_errors.get('qualification'):
        return bundle['invalid_qualification']
    if validation_errors.get('name'):
        return bundle['invalid_name']
    return bundle.get(field_name, bundle['contact'])


# wrkng on finalize_ai_response
def finalize_ai_response(session_id, user_message, preferred_language, ai_response, courses):
    session = sessions[session_id]
    extracted_data, validation_errors = extract_user_details(
        user_message,
        session['data'],
        courses,
        session.get('last_requested_field')
    )

    ai_extracted = sanitize_ai_extracted_data(ai_response.get('extracted_data', {}), courses)

    for key, value in ai_extracted.items():
        extracted_data.setdefault(key, value)

    if extracted_data:
        session['data'].update(extracted_data)

    missing_fields = get_missing_fields(session['data'])
    next_field = missing_fields[0] if missing_fields else None

    clean_response = strip_follow_up_question(ai_response.get('response', ''))
    follow_up_question = build_follow_up_question(next_field, preferred_language, session['data'], validation_errors) if (next_field or validation_errors) else None

    if follow_up_question:
        clean_response = f"{clean_response}\n\n<div class=\"highlight-question\">{follow_up_question}</div>" if clean_response else f"<div class=\"highlight-question\">{follow_up_question}</div>"

    ai_response['response'] = clean_response
    ai_response['extracted_data'] = extracted_data
    ai_response['ready_to_submit'] = not missing_fields and not validation_errors
    
    if session['data'].get('interested_course'):
        ai_response['follow_up_suggestions'] = []

    session['last_requested_field'] = next_field
    session['messages'].append({'role': 'assistant', 'content': ai_response.get('response', '')})

    if ai_response['ready_to_submit'] and not session.get('inquiry_created'):
        create_inquiry_from_session(session_id)
        session['inquiry_created'] = True
        ai_response['inquiry_submitted'] = True

    return ai_response

# mang user seesion
def create_inquiry_from_session(session_id):
    session = sessions[session_id]
    data = session['data']
    
    summary = f"Inquiry from {data.get('name', 'Unknown')}. Interested in {data.get('interested_course', 'Not specified')}."
    user_query = ' | '.join(
        normalize_whitespace(message.get('content', ''))
        for message in session.get('messages', [])
        if message.get('role') == 'user'
    )
    
    probability = calculate_admission_probability(data)
    
    conn = get_db()
    conn.execute('''INSERT INTO inquiries 
        (name, email, contact, qualification, interested_course, ai_summary, 
         admission_probability, session_id, percentage_probability, user_query)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (data.get('name'), data.get('email'), data.get('contact'), 
         data.get('qualification'), data.get('interested_course'),
         summary, probability, session_id,
         float(probability.replace('%', '')) if probability else 0.0,
         user_query))
    conn.commit()
    conn.close()

# wrkng on calculate_admission_probability
def calculate_admission_probability(data):
    score = 50  # Base score
    if data.get('qualification'): score += 20
    if data.get('email'): score += 10
    if data.get('interested_course'): score += 20
    return f"{min(score, 95)}%"


@app.route('/api/courses', methods=['GET'])
@require_api_key
# ftech dta function
def get_courses():
    conn = get_db()
    courses = conn.execute('SELECT * FROM courses ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict_from_row(c) for c in courses])

@app.route('/api/courses', methods=['POST'])
@require_api_key
# wrkng on add_course
def add_course():
    data = request.json
    conn = get_db()
    conn.execute('''INSERT INTO courses 
        (course_name, duration, eligibility, fees, key_subjects, admission_process, career_opportunities)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (data['course_name'], data.get('duration'), data.get('eligibility'),
         data.get('fees'), data.get('key_subjects'), data.get('admission_process'),
         data.get('career_opportunities')))
    conn.commit()
    course_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': course_id, 'message': 'Course added successfully'})

@app.route('/api/courses/<int:course_id>', methods=['PUT'])
@require_api_key
# wrkng on update_course
def update_course(course_id):
    data = request.json
    conn = get_db()
    conn.execute('''UPDATE courses SET
        course_name=?, duration=?, eligibility=?, fees=?, key_subjects=?,
        admission_process=?, career_opportunities=?
        WHERE id=?''',
        (data['course_name'], data.get('duration'), data.get('eligibility'),
         data.get('fees'), data.get('key_subjects'), data.get('admission_process'),
         data.get('career_opportunities'), course_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Course updated successfully'})

@app.route('/api/courses/<int:course_id>', methods=['DELETE'])
@require_api_key
# delte functn
def delete_course(course_id):
    conn = get_db()
    conn.execute('DELETE FROM courses WHERE id=?', (course_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Course deleted successfully'})


@app.route('/api/gallery', methods=['GET'])
@require_api_key
# ftech dta function
def get_gallery():
    conn = get_db()
    gallery = conn.execute('SELECT * FROM campus_gallery ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict_from_row(g) for g in gallery])

@app.route('/api/gallery', methods=['POST'])
@require_api_key
# wrkng on add_gallery
def add_gallery():
    data = request.json
    conn = get_db()
    conn.execute('''INSERT INTO campus_gallery (title, tag, image_path)
        VALUES (?, ?, ?)''',
        (data['title'], data.get('tag'), data.get('image_path')))
    conn.commit()
    gallery_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': gallery_id, 'message': 'Gallery item added successfully'})

@app.route('/api/gallery/upload', methods=['POST'])
@require_api_key
# file upld hndler
def upload_gallery_image():
    """Upload image file to server"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP'}), 400
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = timestamp + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        title = request.form.get('title')
        tag = request.form.get('tag', '')
        
        image_url = f'/uploads/gallery/{filename}'
        conn = get_db()
        conn.execute('''INSERT INTO campus_gallery (title, tag, image_path)
            VALUES (?, ?, ?)''', (title, tag, image_url))
        conn.commit()
        gallery_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        return jsonify({
            'id': gallery_id,
            'message': 'Image uploaded successfully',
            'image_path': image_url
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/gallery/<int:gallery_id>', methods=['DELETE'])
@require_api_key
# delte functn
def delete_gallery(gallery_id):
    conn = get_db()
    gallery_item = conn.execute('SELECT image_path FROM campus_gallery WHERE id=?', (gallery_id,)).fetchone()
    
    conn.execute('DELETE FROM campus_gallery WHERE id=?', (gallery_id,))
    conn.commit()
    conn.close()
    
    if gallery_item and gallery_item[0].startswith('/uploads/'):
        try:
            filepath = gallery_item[0].replace('/uploads/gallery/', '')
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], filepath)
            if os.path.exists(full_path):
                os.remove(full_path)
        except:
            pass  # Continue even if file deletion fails
    
    return jsonify({'message': 'Gallery item deleted successfully'})


@app.route('/api/companies', methods=['GET'])
@require_api_key
# ftech dta function
def get_companies():
    conn = get_db()
    companies = conn.execute('SELECT * FROM companies ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict_from_row(c) for c in companies])

@app.route('/api/companies', methods=['POST'])
@require_api_key
# wrkng on add_company
def add_company():
    data = request.json
    conn = get_db()
    conn.execute('''INSERT INTO companies (company_name, industry_name, location, website, notes)
        VALUES (?, ?, ?, ?, ?)''',
        (data['company_name'], data.get('industry_name'), data.get('location'),
         data.get('website'), data.get('notes')))
    conn.commit()
    company_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': company_id, 'message': 'Company added successfully'})

@app.route('/api/companies/<int:company_id>', methods=['DELETE'])
@require_api_key
# delte functn
def delete_company(company_id):
    conn = get_db()
    conn.execute('DELETE FROM companies WHERE id=?', (company_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Company deleted successfully'})


@app.route('/api/students', methods=['GET'])
@require_api_key
# ftech dta function
def get_students():
    conn = get_db()
    students = conn.execute('SELECT * FROM students_placed ORDER BY year DESC, created_at DESC').fetchall()
    conn.close()
    return jsonify([dict_from_row(s) for s in students])

@app.route('/api/students', methods=['POST'])
@require_api_key
# wrkng on add_student
def add_student():
    data = request.json
    conn = get_db()
    conn.execute('''INSERT INTO students_placed (student_name, course_name, company_name, package, year)
        VALUES (?, ?, ?, ?, ?)''',
        (data['student_name'], data.get('course_name'), data.get('company_name'),
         data.get('package'), data.get('year')))
    conn.commit()
    student_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': student_id, 'message': 'Student record added successfully'})

@app.route('/api/students/<int:student_id>', methods=['DELETE'])
@require_api_key
# delte functn
def delete_student(student_id):
    conn = get_db()
    conn.execute('DELETE FROM students_placed WHERE id=?', (student_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Student record deleted successfully'})


@app.route('/api/inquiries', methods=['GET'])
@require_api_key
# ftech dta function
def get_inquiries():
    year = request.args.get('year')
    search = request.args.get('search', '')
    
    conn = get_db()
    query = 'SELECT * FROM inquiries WHERE 1=1'
    params = []
    
    if year:
        query += ' AND strftime("%Y", created_at) = ?'
        params.append(year)
    
    if search:
        query += ' AND (name LIKE ? OR email LIKE ? OR contact LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    query += ' ORDER BY percentage_probability DESC, created_at DESC'
    
    inquiries = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict_from_row(i) for i in inquiries])

@app.route('/api/inquiries/<int:inquiry_id>', methods=['PUT'])
@require_api_key
# wrkng on update_inquiry
def update_inquiry(inquiry_id):
    data = request.json
    conn = get_db()
    
    fields = []
    values = []
    for key, value in data.items():
        if key != 'id':
            fields.append(f'{key}=?')
            values.append(value)
    
    values.append(inquiry_id)
    query = f"UPDATE inquiries SET {', '.join(fields)} WHERE id=?"
    
    conn.execute(query, values)
    conn.commit()
    conn.close()
    return jsonify({'message': 'Inquiry updated successfully'})

@app.route('/api/inquiries/export', methods=['GET'])
@require_api_key
# wrkng on export_inquiries
def export_inquiries():
    try:
        print("=== Export started ===")
        year = request.args.get('year')
        export_format = request.args.get('format', 'csv')  # csv or excel
        
        conn = get_db()
        query = 'SELECT * FROM inquiries'
        params = []
        
        if year:
            query += ' WHERE strftime("%Y", created_at) = ?'
            params.append(year)
        
        query += ' ORDER BY created_at DESC'
        
        inquiries = conn.execute(query, params).fetchall()
        conn.close()
        
        print(f"Found {len(inquiries)} inquiries")
        
        data = [dict_from_row(i) for i in inquiries]
        
        if not data:
            print("No data found")
            return jsonify({'error': 'No inquiries found'}), 404
        
        print(f"Converted to {len(data)} dictionaries")
        
        df = pd.DataFrame(data)
        print(f"DataFrame created with columns: {list(df.columns)}")
        
        column_order = ['id', 'name', 'email', 'contact', 'qualification', 'interested_course', 
                       'percentage_probability', 'admission_probability', 'status', 'user_query', 
                       'ai_summary', 'session_id', 'created_at']
        
        existing_columns = [col for col in column_order if col in df.columns]
        df = df[existing_columns]
        print(f"Reordered columns: {list(df.columns)}")
        
        df = df.fillna('')
        
        column_names = {
            'id': 'ID', 
            'name': 'Name', 
            'email': 'Email', 
            'contact': 'Contact', 
            'qualification': 'Qualification', 
            'interested_course': 'Interested Course',
            'percentage_probability': 'Probability %', 
            'admission_probability': 'Admission Probability', 
            'status': 'Status',
            'user_query': 'User Query',
            'ai_summary': 'AI Summary',
            'session_id': 'Session ID', 
            'created_at': 'Created At'
        }
        df.rename(columns={k: v for k, v in column_names.items() if k in df.columns}, inplace=True)
        print("Columns renamed")
        
        if export_format == 'excel':
            try:
                output = BytesIO()
                print("Creating Excel file...")
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Inquiries')
                output.seek(0)
                
                filename = f'vishwalata_inquiries_{year or "all"}_{datetime.now().strftime("%Y%m%d")}.xlsx'
                print(f"Sending Excel file: {filename}")
                
                return send_file(
                    output,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    as_attachment=True,
                    download_name=filename
                )
            except Exception as excel_error:
                print(f"Excel export failed: {excel_error}, falling back to CSV")
                export_format = 'csv'
        
        if export_format == 'csv':
            output = BytesIO()
            print("Creating CSV file...")
            csv_data = df.to_csv(index=False, encoding='utf-8-sig')  # utf-8-sig for Excel compatibility
            output.write(csv_data.encode('utf-8-sig'))
            output.seek(0)
            
            filename = f'vishwalata_inquiries_{year or "all"}_{datetime.now().strftime("%Y%m%d")}.csv'
            print(f"Sending CSV file: {filename}")
            
            return send_file(
                output,
                mimetype='text/csv',
                as_attachment=True,
                download_name=filename
            )
            
    except Exception as e:
        print(f"Export Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@app.route('/api/stats', methods=['GET'])
@require_api_key
# ftech dta function
def get_stats():
    conn = get_db()
    
    stats = {
        'total_courses': conn.execute('SELECT COUNT(*) FROM courses').fetchone()[0],
        'total_inquiries': conn.execute('SELECT COUNT(*) FROM inquiries').fetchone()[0],
        'total_placements': conn.execute('SELECT COUNT(*) FROM students_placed').fetchone()[0],
        'total_companies': conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        'pending_inquiries': conn.execute('SELECT COUNT(*) FROM inquiries WHERE status="pending"').fetchone()[0],
        'high_probability': conn.execute('SELECT COUNT(*) FROM inquiries WHERE percentage_probability >= 70').fetchone()[0],
        'recent_inquiries': [dict_from_row(i) for i in conn.execute('SELECT * FROM inquiries ORDER BY created_at DESC LIMIT 5').fetchall()],
        'course_interest': [dict_from_row(c) for c in conn.execute('''
            SELECT interested_course as course, COUNT(*) as count 
            FROM inquiries 
            WHERE interested_course IS NOT NULL 
            GROUP BY interested_course 
            ORDER BY count DESC LIMIT 5
        ''').fetchall()]
    }
    
    conn.close()
    return jsonify(stats)

init_db()

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
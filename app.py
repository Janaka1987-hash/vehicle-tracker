from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import os
import hashlib
import re
from datetime import datetime
from PIL import Image
import pytesseract

app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key_secure_123'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

latest_locations = {}

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            vehicle_code TEXT,
            is_active INTEGER DEFAULT 0,
            receipt TEXT
        )
    ''')
    # එකම රිසිට් එක දෙවරක් Upload කිරීම වැළැක්වීමට වගුවක්
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS used_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT UNIQUE,
            receipt_signature TEXT UNIQUE,
            username TEXT,
            uploaded_at TEXT
        )
    ''')
    cursor.execute("SELECT * FROM users WHERE username = ?", ('janaka@123',))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, vehicle_code, is_active, receipt) VALUES (?, ?, ?, ?, ?, ?)",
                       ('janaka@123', '19871019', 'owner', 'MASTER', 1, 'Owner Account (Free)'))
    conn.commit()
    conn.close()

init_db()

def verify_receipt_image(filepath, role):
    try:
        img = Image.open(filepath)
        text = pytesseract.image_to_string(img)
        clean_text = text.replace(',', '').replace(' ', '').lower()
        raw_lower = text.lower()

        # 1. ගිණුම් අංකය පරීක්ෂාව (100850422975 හෝ අග ඉලක්කම් 2975)
        if '2975' not in clean_text:
            return False, "ගිණුම් අංකයේ අග ඉලක්කම් 2975 (100850422975) රිසිට්පතේ පැහැදිලිව නොමැත!", None

        # 2. මුදල් ප්‍රමාණය පරීක්ෂාව (රියදුරු: 500, මගියා: 300)
        expected_amount = '500' if role == 'driver' else '300'
        if expected_amount not in clean_text:
            return False, f"නිවැරදි මුදල් ප්‍රමාණය (Rs. {expected_amount}) රිසිට්පතේ සඳහන් වී නොමැත!", None

        # 3. මූල්‍යමය ගනුදෙනුවක් බව තහවුරු කිරීම
        financial_keywords = ['deposit', 'transfer', 'success', 'completed', 'lkr', 'rs', 'bank', 'account', 'credited', 'payment', 'slip', 'receipt']
        if not any(word in raw_lower for word in financial_keywords):
            return False, "මෙය වලංගු මූල්‍යමය ගනුදෙනු රිසිට්පතක් ලෙස හඳුනාගත නොහැක!", None

        # 4. අද දිනය පරීක්ෂාව (ශ්‍රී ලංකා වේලාව අනුව +5:30)
        # විවිධ බැංකු රිසිට් වල දිනය සටහන් වන ආකාර (උදා: 2026-11-16, 16/11/2026, 16-11-2026, 16 Nov 2026)
        now = datetime.utcnow()
        # UTC + 5:30
        from datetime import timedelta
        sl_now = now + timedelta(hours=5, minutes=30)
        
        d_formats = [
            sl_now.strftime("%Y-%m-%d"),
            sl_now.strftime("%Y/%m/%d"),
            sl_now.strftime("%d-%m-%Y"),
            sl_now.strftime("%d/%m/%Y"),
            sl_now.strftime("%d.%m.%Y"),
            sl_now.strftime("%d %b %Y").lower(),
            sl_now.strftime("%d-%b-%Y").lower(),
            sl_now.strftime("%b %d, %Y").lower()
        ]
        if not any(df in raw_lower for df in d_formats):
            return False, f"රිසිට්පතේ දිනය අද දිනය ({sl_now.strftime('%Y-%m-%d')}) සමඟ නොගැලපේ!", None

        # 5. වේලාව (Time) හඳුනාගෙන Unique Signature එකක් සෑදීම (එකම රිසිට් එක දෙවරක් දැමීම වැළැක්වීමට)
        time_match = re.search(r'\b([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?\b', text)
        extracted_time = time_match.group(0) if time_match else "NO_TIME"
        signature = f"{sl_now.strftime('%Y-%m-%d')}_{extracted_time}_{expected_amount}_2975"

        return True, "සාර්ථකයි", signature

    except Exception as e:
        return False, "රිසිට්පත කියවීමේදී දෝෂයක් ඇති විය. කරුණාකර පැහැදිලි පින්තූරයක් යොදන්න.", None

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return redirect(url_for('login'))
    if 'username' not in session:
        return redirect(url_for('login'))
    
    role = session.get('role')
    is_active = session.get('is_active', 0)
    
    if role == 'owner':
        return redirect(url_for('owner_dashboard'))
    if is_active == 0:
        return redirect(url_for('payment'))
    
    if role == 'driver':
        return render_template('driver_map.html', username=session['username'], vehicle_code=session.get('vehicle_code'))
    else:
        return render_template('passenger_map.html', username=session['username'], vehicle_code=session.get('vehicle_code'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session.clear()
            session['username'] = user[1]
            session['role'] = user[3]
            session['vehicle_code'] = user[4]
            session['is_active'] = user[5]
            
            if user[3] == 'owner':
                return redirect(url_for('owner_dashboard'))
            elif user[5] == 1:
                return redirect(url_for('index'))
            else:
                return redirect(url_for('payment'))
        else:
            return "<script>alert('වැරදි නමක් හෝ මුරපදයක්! කරුණාකර නැවත උත්සාහ කරන්න.'); window.location.href='/login';</script>"
            
    if 'username' in session:
        return redirect(url_for('index'))
            
    return render_template('login.html')

@app.route('/owner_dashboard')
def owner_dashboard():
    if 'username' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, role, vehicle_code, is_active, receipt FROM users")
    users = cursor.fetchall()
    conn.close()
    
    return render_template('owner_dashboard.html', username=session['username'], users=users)

@app.route('/toggle_status/<int:user_id>')
def toggle_status(user_id):
    if 'username' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        current_status = result[0]
        new_status = 0 if current_status == 1 else 1
        cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))
        conn.commit()
    
    conn.close()
    return redirect(url_for('owner_dashboard'))

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    if 'username' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    if request.method == 'POST':
        new_username = request.form['username']
        new_password = request.form['password']
        new_vehicle_code = request.form['vehicle_code'].strip()
        
        cursor.execute("UPDATE users SET username = ?, password = ?, vehicle_code = ? WHERE id = ?",
                       (new_username, new_password, new_vehicle_code, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('owner_dashboard'))
        
    cursor.execute("SELECT id, username, password, role, vehicle_code FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    return render_template('edit_user.html', user=user)

@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'username' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if user and user[0] != 'owner':
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        
    conn.close()
    return redirect(url_for('owner_dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        vehicle_code = request.form.get('vehicle_code', '').strip()
        
        try:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password, role, vehicle_code, is_active) VALUES (?, ?, ?, ?, 0)", 
                           (username, password, role, vehicle_code))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except Exception as e:
            return "මෙම නම දැනටමත් භාවිතා කර ඇත හෝ දෝෂයක් සිදු විය!"
    return render_template('register.html')

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    role = session.get('role')
    fee = 500 if role == 'driver' else 300
    
    if request.method == 'POST':
        if 'receipt' in request.files:
            file = request.files['receipt']
            if file.filename != '':
                # 1. File Hash එක ගණනය කර පෙර භාවිතා කර ඇත්දැයි බැලීම
                file_bytes = file.read()
                file_hash = hashlib.sha256(file_bytes).hexdigest()
                file.seek(0)

                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM used_receipts WHERE file_hash = ?", (file_hash,))
                if cursor.fetchone():
                    conn.close()
                    return "<script>alert('මෙම රිසිට්පත දැනටමත් වෙනත් ගිණුමක් සඳහා භාවිතා කර ඇත! නැවත Upload කළ නොහැක.'); window.location.href='/payment';</script>"

                filename = f"{session['username']}_{int(datetime.now().timestamp())}_{file.filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                # 2. OCR මඟින් රිසිට්පතේ දත්ත පරීක්ෂා කිරීම
                is_valid, message, signature = verify_receipt_image(filepath, role)
                if not is_valid:
                    os.remove(filepath) # වලංගු නොවන ෆයිල් එක ඉවත් කිරීම
                    conn.close()
                    return f"<script>alert('අසාර්ථකයි: {message}'); window.location.href='/payment';</script>"

                # 3. එකම වේලාව සහ දිනය ඇති රිසිට් එකක් දෙවරක් දැමීම වැළැක්වීම
                if signature and "NO_TIME" not in signature:
                    cursor.execute("SELECT * FROM used_receipts WHERE receipt_signature = ?", (signature,))
                    if cursor.fetchone():
                        os.remove(filepath)
                        conn.close()
                        return "<script>alert('මෙම ගනුදෙනු රිසිට්පත දැනටමත් භාවිතා කර ඇත! එකම රිසිට්පත දෙවරක් භාවිතා කළ නොහැක.'); window.location.href='/payment';</script>"

                # සියල්ල නිවැරදි නම් රිසිට්පත සේව් කර ගිණුම සක්‍රීය කිරීම
                cursor.execute("INSERT INTO used_receipts (file_hash, receipt_signature, username, uploaded_at) VALUES (?, ?, ?, ?)",
                               (file_hash, signature, session['username'], str(datetime.now())))
                cursor.execute("UPDATE users SET is_active = 1, receipt = ? WHERE username = ?", 
                               (filename, session['username']))
                conn.commit()
                conn.close()
                
                session['is_active'] = 1
                return f"<script>alert('ගෙවීම තහවුරු විය! ඔබේ ගිණුම සක්‍රීය කරන ලදී.'); window.location.href='/';</script>"
                
    return render_template('payment.html', fee=fee, username=session['username'])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Socket.io Rooms සහ Multi-Passenger Location Handling ---

@socketio.on('join')
def on_join(data):
    vehicle_code = str(data.get('vehicle_code', '')).strip()
    if vehicle_code:
        join_room(vehicle_code)
        if vehicle_code in latest_locations:
            room_data = latest_locations[vehicle_code]
            if 'driver' in room_data:
                emit('broadcast_location', room_data['driver'])
            if 'passengers' in room_data:
                for p_user, p_data in room_data['passengers'].items():
                    emit('broadcast_location', p_data)

@socketio.on('update_location')
def handle_location(data):
    vehicle_code = str(data.get('vehicle_code', '')).strip()
    role = data.get('role')
    username = data.get('username')
    if vehicle_code and role and username:
        if vehicle_code not in latest_locations:
            latest_locations[vehicle_code] = {'passengers': {}}
        
        if role == 'driver':
            latest_locations[vehicle_code]['driver'] = data
        elif role == 'passenger':
            if 'passengers' not in latest_locations[vehicle_code]:
                latest_locations[vehicle_code]['passengers'] = {}
            latest_locations[vehicle_code]['passengers'][username] = data
            
        emit('broadcast_location', data, room=vehicle_code)

@socketio.on('update_attendance')
def handle_attendance(data):
    vehicle_code = str(data.get('vehicle_code', '')).strip()
    if vehicle_code:
        emit('broadcast_attendance', data, room=vehicle_code)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)

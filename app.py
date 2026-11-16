from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_secret_key_secure_123'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# වාහන කෝඩ් අනුව රියදුරු සහ සියලුම මගීන්ගේ ලොකේෂන් මතක තබා ගැනීමට
# ව්‍යුහය: { '1000': { 'driver': {...}, 'passengers': { 'user1': {...}, 'user2': {...} } } }
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
    cursor.execute("SELECT * FROM users WHERE username = ?", ('janaka@123',))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, vehicle_code, is_active, receipt) VALUES (?, ?, ?, ?, ?, ?)",
                       ('janaka@123', '19871019', 'owner', 'MASTER', 1, 'Owner Account (Free)'))
    conn.commit()
    conn.close()

init_db()

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
                filename = file.filename
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
                conn = sqlite3.connect('database.db')
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET is_active = 1, receipt = ? WHERE username = ?", 
                               (filename, session['username']))
                conn.commit()
                conn.close()
                
                session['is_active'] = 1
                return redirect(url_for('index'))
                
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

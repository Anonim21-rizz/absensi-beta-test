import os, uuid, time, io, base64
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, jsonify
import qrcode
import sqlite3

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'absensi.db')
TOKEN_EXPIRY = 15

# Zona waktu WIB (UTC+7)
WIB = timezone(timedelta(hours=7))

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, nama TEXT NOT NULL UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, created_at REAL NOT NULL, used INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS absensi (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, waktu TEXT NOT NULL, token TEXT NOT NULL)')
    conn.commit()
    conn.close()

@app.route('/')
def admin_page():
    return render_template('admin.html')

@app.route('/scan')
def scan_page():
    return render_template('scan.html')

@app.route('/generate_qr')
def generate_qr():
    token = f"{uuid.uuid4().hex}_{int(time.time())}"
    created_at = time.time()
    conn = get_db()
    conn.execute('INSERT INTO tokens (token, created_at, used) VALUES (?, ?, 0)', (token, created_at))
    conn.commit()
    # cleanup old tokens
    conn.execute('DELETE FROM tokens WHERE created_at < ?', (time.time() - 120,))
    conn.commit()
    conn.close()

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    return jsonify({'success': True, 'qr_image': f'data:image/png;base64,{img_b64}', 'token': token, 'created_at': created_at})

@app.route('/submit_absen', methods=['POST'])
def submit_absen():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Data tidak valid'}), 400
    token = (data.get('token') or '').strip()
    user_name = (data.get('user_name') or '').strip()
    if not token or not user_name:
        return jsonify({'success': False, 'message': 'Token dan nama harus diisi'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM tokens WHERE token = ?', (token,))
    tok = c.fetchone()
    if not tok:
        conn.close()
        return jsonify({'success': False, 'message': 'Token tidak valid!'}), 400
    if tok['used'] == 1:
        conn.close()
        return jsonify({'success': False, 'message': 'Token sudah digunakan!'}), 400
    if time.time() - tok['created_at'] > TOKEN_EXPIRY:
        conn.close()
        return jsonify({'success': False, 'message': 'QR Code sudah expired! Scan QR yang baru.'}), 400

    c.execute('SELECT id FROM users WHERE nama = ?', (user_name,))
    u = c.fetchone()
    if u:
        user_id = u['id']
    else:
        c.execute('INSERT INTO users (nama) VALUES (?)', (user_name,))
        user_id = c.lastrowid

    today = datetime.now(WIB).strftime('%Y-%m-%d')
    c.execute('SELECT id FROM absensi WHERE user_id = ? AND waktu LIKE ?', (user_id, f"{today}%"))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': f'{user_name} sudah absensi hari ini!'}), 400

    c.execute('UPDATE tokens SET used = 1 WHERE token = ?', (token,))
    waktu = datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')
    c.execute('INSERT INTO absensi (user_id, waktu, token) VALUES (?, ?, ?)', (user_id, waktu, token))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': f'Absensi berhasil untuk {user_name}!', 'waktu': waktu})

@app.route('/get_absen')
def get_absen():
    today = datetime.now(WIB).strftime('%Y-%m-%d')
    conn = get_db()
    rows = conn.execute('SELECT a.id, u.nama, a.waktu FROM absensi a JOIN users u ON a.user_id = u.id WHERE a.waktu LIKE ? ORDER BY a.waktu DESC', (f"{today}%",)).fetchall()
    conn.close()
    data = [{'id': r['id'], 'nama': r['nama'], 'waktu': r['waktu']} for r in rows]
    return jsonify({'success': True, 'tanggal': today, 'total': len(data), 'data': data})

@app.route('/delete_absen/<int:absen_id>', methods=['DELETE'])
def delete_absen(absen_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM absensi WHERE id = ?', (absen_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Data tidak ditemukan'}), 404
    c.execute('DELETE FROM absensi WHERE id = ?', (absen_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Data absensi berhasil dihapus'})

@app.route('/clear_absen', methods=['DELETE'])
def clear_absen():
    today = datetime.now(WIB).strftime('%Y-%m-%d')
    conn = get_db()
    conn.execute('DELETE FROM absensi WHERE waktu LIKE ?', (f"{today}%",))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Semua absensi hari ini berhasil dihapus'})

# Initialize DB at module level so it works on PythonAnywhere (WSGI)
# PythonAnywhere does NOT run the __main__ block
init_db()

if __name__ == '__main__':
    print("=" * 50)
    print("  SISTEM ABSENSI QR CODE")
    print("  Admin : http://localhost:5000")
    print("  Scan  : http://<IP>:5000/scan")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)

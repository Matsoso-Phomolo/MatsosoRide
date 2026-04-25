"""
Urban Cab — Flask Web Application (MySQL)
Maseru CBD + MSU Local Passenger Transportation System
Anonymous passenger model: name + phone captured on ride, no account required.
8 tables: Locations, Payment_Methods, Fares, Drivers, Admin_Users,
          Rides, Vehicle_Status, Ride_Reports

Requirements: pip install flask werkzeug flask-mysqldb
Database:     Run urban_cab_mysql.sql against your MySQL server first.
Config:       Set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME env vars,
              or edit the app.config lines directly in this file.
"""
import os, hashlib, secrets, re, datetime, textwrap
from flask_mysqldb import MySQL
import MySQLdb.cursors
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, g, jsonify, make_response)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ── MySQL config ─────────────────────────────────────────────
app.config['MYSQL_HOST']     = os.environ.get('DB_HOST',     'localhost')
app.config['MYSQL_USER']     = os.environ.get('DB_USER',     'root')
app.config['MYSQL_PASSWORD'] = os.environ.get('DB_PASSWORD', '@Master5725#')
app.config['MYSQL_DB']       = os.environ.get('DB_NAME',     'lipalangoang')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)


def repair_seed_data():
    """Normalize known seeded values that were imported with bad characters."""
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            """UPDATE Drivers
               SET first_name=%s, last_name=%s
               WHERE phone_number=%s
                 AND (first_name<>%s OR last_name<>%s)""",
            ("Rets'elisitsoe", "Tau", "+26658200002", "Rets'elisitsoe", "Tau")
        )
        mysql.connection.commit()
        cur.close()
    except Exception:
        pass


@app.before_request
def run_startup_repairs():
    if app.config.get('_seed_repairs_done'):
        return
    repair_seed_data()
    app.config['_seed_repairs_done'] = True

# ── DB helpers ────────────────────────────────────────────────
def q(sql, args=(), one=False):
    """Execute a SELECT and return list of dicts (or one dict)."""
    cur = mysql.connection.cursor()
    cur.execute(sql, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def m(sql, args=()):
    """Execute INSERT / UPDATE / DELETE, commit, return lastrowid."""
    cur = mysql.connection.cursor()
    cur.execute(sql, args)
    mysql.connection.commit()
    lid = cur.lastrowid
    cur.close()
    return lid

def hash_pw(pw):   return hashlib.sha256(pw.encode()).hexdigest()

def call_proc(name, in_args=()):
    """Call a stored procedure with IN args.
    Returns (out_dict, rows) where out_dict holds all @out_* variables.
    For procedures that return a result set, rows contains the rows.
    """
    cur = mysql.connection.cursor()
    # Build OUT variable placeholders
    # Convention: last N args that are None are OUT args
    in_count  = len([a for a in in_args if a is not None])
    out_count = len([a for a in in_args if a is None])
    placeholders = ','.join(
        [f'%s'] * in_count +
        [f'@out_{i}' for i in range(out_count)]
    )
    cur.execute(f'CALL {name}({placeholders})', [a for a in in_args if a is not None])
    rows = cur.fetchall()
    cur.close()
    # Fetch OUT variable values
    if out_count:
        out_vars = ', '.join(f'@out_{i}' for i in range(out_count))
        cur2 = mysql.connection.cursor()
        cur2.execute(f'SELECT {out_vars}')
        out_row = cur2.fetchone()
        cur2.close()
        out_dict = {f'out_{i}': v for i,v in enumerate(out_row.values())} if out_row else {}
    else:
        out_dict = {}
    return out_dict, rows
def check_pw(p,h): return hash_pw(p) == h


def pdf_safe(text):
    """Convert text into a PDF-safe single line string."""
    if text is None:
        return ''
    text = str(text).replace('\r', ' ').replace('\n', ' ')
    text = (
        text.replace('\u2018', "'")
            .replace('\u2019', "'")
            .replace('\u0060', "'")
            .replace('\u00b4', "'")
    )
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_simple_pdf(title, lines):
    """Create a minimal one-page PDF with plain text content."""
    commands = [
        'BT',
        '/F1 18 Tf',
        '50 790 Td',
        f'({pdf_safe(title)}) Tj',
        '0 -26 Td',
        '/F1 11 Tf'
    ]

    for raw_line in lines[:45]:
        wrapped = textwrap.wrap(str(raw_line), width=92) or ['']
        for part in wrapped:
            commands.append(f'({pdf_safe(part)}) Tj')
            commands.append('0 -15 Td')

    commands.append('ET')
    stream_text = '\n'.join(commands)
    stream_bytes = stream_text.encode('latin-1', 'replace')

    objects = []
    objects.append(b'1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n')
    objects.append(b'2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n')
    objects.append(b'3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n')
    objects.append(b'4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n')
    objects.append(
        f'5 0 obj << /Length {len(stream_bytes)} >> stream\n'.encode('ascii') +
        stream_bytes +
        b'\nendstream endobj\n'
    )

    pdf = b'%PDF-1.4\n'
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj

    xref_pos = len(pdf)
    pdf += f'xref\n0 {len(offsets)}\n'.encode('ascii')
    pdf += b'0000000000 65535 f \n'
    for offset in offsets[1:]:
        pdf += f'{offset:010d} 00000 n \n'.encode('ascii')
    pdf += (
        f'trailer << /Size {len(offsets)} /Root 1 0 R >>\n'
        f'startxref\n{xref_pos}\n%%EOF'
    ).encode('ascii')
    return pdf

# ── Validation ────────────────────────────────────────────────
def val_phone(p): return bool(re.match(r'^\+?[0-9]{8,15}$', p.replace(' ','')))
def val_email(e): return bool(re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', e)) if e else True
def val_pw(p):    return len(p) >= 6
def val_plate(p): return bool(re.match(r'^[A-Z0-9 \-]{4,12}$', p.upper()))
def val_lic(l):   return len(l.strip()) >= 4
def val_name(n):  return len(n.strip()) >= 2

def get_fare(pickup_id, dropoff_id):
    """Look up the fixed fare for two location IDs via the Fares table."""
    row = q("""SELECT f.amount FROM Fares f
        JOIN Locations pu ON pu.area_zone = f.zone_from
        JOIN Locations dr ON dr.area_zone = f.zone_to
        WHERE pu.location_id=%s AND dr.location_id=%s""",
        (pickup_id, dropoff_id), one=True)
    return float(row['amount']) if row else None

# ── Auth decorator ────────────────────────────────────────────
def auth(role=None):
    def dec(f):
        @wraps(f)
        def wrap(*a, **kw):
            if 'uid' not in session:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Access denied.', 'danger')
                return redirect(url_for('home'))
            return f(*a, **kw)
        return wrap
    return dec

# ── DB init ───────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════
#  SHARED ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    if 'uid' in session:
        return redirect(url_for('home'))
    return render_template('landing.html')

@app.route('/home')
def home():
    role = session.get('role')
    if role == 'driver': return redirect(url_for('driver_home'))
    if role == 'admin':  return redirect(url_for('admin_home'))
    return redirect(url_for('index'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        role  = request.form.get('role','driver')
        ident = request.form.get('identifier','').strip()
        pw    = request.form.get('password','')
        if not ident or not pw:
            flash('Please enter your credentials.', 'danger')
            return render_template('login.html', role=role, ident=ident)
        if role == 'driver':
            u = q("SELECT * FROM Drivers WHERE phone_number=%s", (ident,), one=True)
            if u and check_pw(pw, u['password_hash']):
                session.update({'uid': u['driver_id'], 'role': 'driver',
                                'name': f"{u['first_name']} {u['last_name']}"})
                flash(f"Welcome, {u['first_name']}!", 'success')
                return redirect(url_for('driver_home'))
        elif role == 'admin':
            u = q("SELECT * FROM Admin_Users WHERE username=%s OR email=%s", (ident, ident), one=True)
            if u and check_pw(pw, u['password_hash']):
                session.update({'uid':u['admin_id'], 'role':'admin', 'name':u['username']})
                flash('Admin login successful.', 'success')
                return redirect(url_for('admin_home'))
        flash('Incorrect credentials. Please try again.', 'danger')
        return render_template('login.html', role=role, ident=ident)
    return render_template('login.html', role='driver', ident='')

@app.route('/logout')
def logout():
    name = session.get('name','')
    session.clear()
    flash(f'Goodbye, {name}! You have been logged out.', 'info')
    return redirect(url_for('index'))

# ═══════════════════════════════════════════════════════════════
#  PUBLIC — BOOK A RIDE  (no login needed)
# ═══════════════════════════════════════════════════════════════
@app.route('/book', methods=['GET','POST'])
def book():
    locations = q("SELECT * FROM Locations WHERE is_active=1 ORDER BY area_zone,location_name")
    methods   = q("SELECT * FROM Payment_Methods WHERE is_active=1")
    if request.method == 'POST':
        name    = request.form.get('passenger_name','').strip()
        phone   = request.form.get('passenger_phone','').strip()
        pickup  = request.form.get('pickup','')
        dropoff = request.form.get('dropoff','')
        pay     = request.form.get('payment','')
        notes   = request.form.get('notes','').strip()
        errors  = []
        if not val_name(name):    errors.append('Please enter your full name (at least 2 characters).')
        if not phone:             errors.append('Phone number is required.')
        elif not val_phone(phone):errors.append('Enter a valid phone number (e.g. +26657123456).')
        if not pickup:            errors.append('Please select a pickup location.')
        if not dropoff:           errors.append('Please select a destination.')
        if pickup and dropoff and pickup == dropoff:
            errors.append('Pickup and destination cannot be the same location.')
        if not pay:               errors.append('Please select a payment method.')
        if errors:
            for e in errors: flash(e, 'danger')
            fares = q("SELECT * FROM Fares")
            return render_template('book.html', locations=locations, methods=methods, form=request.form, fares=fares)
        # Look up fixed fare from rate table
        fare = get_fare(int(pickup), int(dropoff))
        if fare is None:
            flash('Could not calculate fare for this route. Please try again.', 'danger')
            return render_template('book.html', locations=locations, methods=methods, form=request.form)

        ride_id = m(
            "INSERT INTO Rides(passenger_name,passenger_phone,pickup_location_id,"
            "dropoff_location_id,payment_method_id,notes,ride_status,fare_amount) VALUES(%s,%s,%s,%s,%s,%s,'REQUESTED',%s)",
            (name, phone, int(pickup), int(dropoff), int(pay), notes, fare)
        )
        flash(f'Ride #{ride_id} booked! Fare: M {fare:.2f}. Show your ride number to track it.', 'success')
        return redirect(url_for('track', ride_id=ride_id))
    fares = q("SELECT * FROM Fares")
    return render_template('book.html', locations=locations, methods=methods, form={}, fares=fares)

@app.route('/track/<int:ride_id>')
def track(ride_id):
    ride = q("SELECT * FROM vw_rides_full WHERE ride_id=%s", (ride_id,), one=True)
    if not ride:
        flash('Ride not found.', 'danger')
        return redirect(url_for('book'))
    return render_template('track.html', ride=ride)

@app.route('/api/ride/<int:ride_id>/status')
def api_status(ride_id):
    ride = q("SELECT ride_status, driver_id FROM Rides WHERE ride_id=%s", (ride_id,), one=True)
    if ride: return jsonify({'status': ride['ride_status'], 'driver_id': ride['driver_id']})
    return jsonify({'error': 'not found'}), 404

# ═══════════════════════════════════════════════════════════════
#  DRIVER ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route('/driver')
@auth('driver')
def driver_home():
    driver   = q("SELECT * FROM Drivers WHERE driver_id=%s", (session['uid'],), one=True)
    pending  = q("SELECT * FROM vw_pending_rides")
    my_rides = q("SELECT * FROM vw_rides_full WHERE driver_id=%s AND ride_status IN ('ACCEPTED','IN_PROGRESS') ORDER BY accepted_at DESC", (session['uid'],))
    stats    = q("""SELECT COUNT(*) as total,
        SUM(CASE WHEN ride_status='COMPLETED' THEN 1 ELSE 0 END) as completed,
        COALESCE(SUM(fare_amount),0) as earned
        FROM Rides WHERE driver_id=%s""", (session['uid'],), one=True)
    return render_template('driver/home.html', driver=driver, pending=pending,
                           my_rides=my_rides, stats=stats)

@app.route('/driver/accept/<int:ride_id>', methods=['POST'])
@auth('driver')
def driver_accept(ride_id):
    cur = mysql.connection.cursor()
    cur.execute("CALL sp_accept_ride(%s, %s, @success, @message)",
                (ride_id, session['uid']))
    cur.fetchall()
    cur.close()
    cur2 = mysql.connection.cursor()
    cur2.execute("SELECT @success, @message")
    row = cur2.fetchone()
    cur2.close()
    if row and row.get('@success'):
        flash(f"Ride #{ride_id} accepted! Head to the pickup location.", 'success')
    else:
        flash(row.get('@message','Ride no longer available.') if row else 'Ride no longer available.', 'warning')
    return redirect(url_for('driver_home'))

@app.route('/driver/start/<int:ride_id>', methods=['POST'])
@auth('driver')
def driver_start(ride_id):
    cur = mysql.connection.cursor()
    cur.execute("CALL sp_start_ride(%s, %s, @success, @message)",
                (ride_id, session['uid']))
    cur.fetchall()
    cur.close()
    cur2 = mysql.connection.cursor()
    cur2.execute("SELECT @success, @message")
    row = cur2.fetchone()
    cur2.close()
    if row and row.get('@success'):
        flash('Ride started! Head to the destination.', 'success')
    else:
        flash(row.get('@message','Could not start ride.') if row else 'Could not start ride.', 'danger')
    return redirect(url_for('driver_home'))

@app.route('/driver/complete/<int:ride_id>', methods=['POST'])
@auth('driver')
def driver_complete(ride_id):
    # Fare was set at booking — driver just marks complete via stored procedure
    cur = mysql.connection.cursor()
    cur.execute("CALL sp_complete_ride(%s, %s, @success, @message, @fare)",
                (ride_id, session['uid']))
    cur.fetchall()
    cur.close()
    cur2 = mysql.connection.cursor()
    cur2.execute("SELECT @success, @message, @fare")
    row = cur2.fetchone()
    cur2.close()
    if row and row.get('@success'):
        fare = float(row.get('@fare') or 0)
        flash(f'Ride completed! Collect M {fare:.2f} from the passenger.', 'success')
    else:
        flash(row.get('@message','Could not complete ride.') if row else 'Could not complete ride.', 'danger')
    return redirect(url_for('driver_home'))

@app.route('/driver/toggle', methods=['POST'])
@auth('driver')
def driver_toggle():
    d   = q("SELECT is_available FROM Drivers WHERE driver_id=%s", (session['uid'],), one=True)
    new = 0 if d['is_available'] else 1
    m("UPDATE Drivers SET is_available=%s WHERE driver_id=%s", (new, session['uid']))
    flash(f"Status: {'Online — you will receive ride requests.' if new else 'Offline.'}", 'info')
    return redirect(url_for('driver_home'))

@app.route('/driver/history')
@auth('driver')
def driver_history():
    search    = request.args.get('q','')
    date_from = request.args.get('date_from','')
    date_to   = request.args.get('date_to','')
    sql  = """SELECT r.*,
        pu.location_name AS pickup_name, dr.location_name AS dropoff_name, pm.method_name
        FROM Rides r
        JOIN Locations pu ON r.pickup_location_id=pu.location_id
        JOIN Locations dr ON r.dropoff_location_id=dr.location_id
        JOIN Payment_Methods pm ON r.payment_method_id=pm.payment_method_id
        WHERE r.driver_id=%s AND r.ride_status='COMPLETED'"""
    args = [session['uid']]
    if search:    sql += " AND (r.passenger_name LIKE %s OR r.passenger_phone LIKE %s)"; args += [f'%{search}%']*2
    if date_from: sql += " AND DATE(r.completed_at)>=%s"; args.append(date_from)
    if date_to:   sql += " AND DATE(r.completed_at)<=%s"; args.append(date_to)
    sql += " ORDER BY r.completed_at DESC"
    rides = q(sql, args)
    total = sum(r['fare_amount'] or 0 for r in rides)
    return render_template('driver/history.html', rides=rides, total=total,
                           search=search, date_from=date_from, date_to=date_to)

@app.route('/driver/profile', methods=['GET','POST'])
@auth('driver')
def driver_profile():
    d = q("SELECT * FROM Drivers WHERE driver_id=%s", (session['uid'],), one=True)
    if request.method == 'POST':
        fn  = request.form.get('first_name','').strip()
        ln  = request.form.get('last_name','').strip()
        vm  = request.form.get('vehicle_model','').strip()
        plt = request.form.get('vehicle_plate','').strip().upper()
        pw  = request.form.get('new_password','')
        pw2 = request.form.get('confirm_password','')
        errors = []
        if not val_name(fn): errors.append('First name must be at least 2 characters.')
        if not val_name(ln): errors.append('Last name must be at least 2 characters.')
        if plt and not val_plate(plt): errors.append('Vehicle plate format: 4–12 alphanumeric characters.')
        if pw and not val_pw(pw):      errors.append('Password must be at least 6 characters.')
        if pw and pw != pw2:           errors.append('Passwords do not match.')
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('driver/profile.html', d=d)
        if pw:
            m("UPDATE Drivers SET first_name=%s,last_name=%s,vehicle_model=%s,vehicle_plate=%s,password_hash=%s "
              "WHERE driver_id=%s", (fn, ln, vm, plt or d['vehicle_plate'], hash_pw(pw), session['uid']))
        else:
            m("UPDATE Drivers SET first_name=%s,last_name=%s,vehicle_model=%s,vehicle_plate=%s WHERE driver_id=%s",
              (fn, ln, vm, plt or d['vehicle_plate'], session['uid']))
        session['name'] = f"{fn} {ln}"
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('driver_profile'))
    return render_template('driver/profile.html', d=d)

# ═══════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════
@app.route('/admin')
@auth('admin')
def admin_home():
    stats = q("""SELECT COUNT(*) as total,
        SUM(CASE WHEN ride_status='COMPLETED'   THEN 1 ELSE 0 END) as completed,
        SUM(CASE WHEN ride_status='CANCELLED'   THEN 1 ELSE 0 END) as cancelled,
        SUM(CASE WHEN ride_status='REQUESTED'   THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN ride_status='IN_PROGRESS' THEN 1 ELSE 0 END) as in_progress,
        COALESCE(SUM(fare_amount),0) as revenue FROM Rides""", one=True)
    drivers_total  = q("SELECT COUNT(*) as c FROM Drivers", one=True)
    drivers_online = q("SELECT COUNT(*) as c FROM Drivers WHERE is_available=1", one=True)
    recent = q("SELECT * FROM vw_rides_full ORDER BY requested_at DESC LIMIT 8")
    top_locs = q("SELECT location_name, pickup_count AS cnt FROM vw_location_demand ORDER BY pickup_count DESC LIMIT 5")
    pay_stats = q("""SELECT pm.method_name, COUNT(r.ride_id) as cnt,
        COALESCE(SUM(r.fare_amount),0) as total
        FROM Payment_Methods pm LEFT JOIN Rides r ON pm.payment_method_id=r.payment_method_id
        GROUP BY pm.payment_method_id""")
    return render_template('admin/home.html', stats=stats,
                           drivers_total=drivers_total, drivers_online=drivers_online,
                           recent=recent, top_locs=top_locs, pay_stats=pay_stats)

# ── Admin: Rides ─────────────────────────────────────────────
@app.route('/admin/rides')
@auth('admin')
def admin_rides():
    search    = request.args.get('q','')
    status    = request.args.get('status','')
    loc_id    = request.args.get('loc_id','')
    date_from = request.args.get('date_from','')
    date_to   = request.args.get('date_to','')
    sql  = """SELECT * FROM vw_rides_full WHERE 1=1"""
    args = []
    if search:
        sql += """ AND (
            passenger_name LIKE %s OR
            passenger_phone LIKE %s OR
            COALESCE(driver_name,'') LIKE %s OR
            pickup_name LIKE %s OR
            dropoff_name LIKE %s
        )"""
        args += [f'%{search}%'] * 5
    if status:
        sql += " AND ride_status=%s"
        args.append(status)
    if loc_id:
        sql += " AND (pickup_location_id=%s OR dropoff_location_id=%s)"
        args += [loc_id] * 2
    if date_from:
        sql += " AND DATE(requested_at)>=%s"
        args.append(date_from)
    if date_to:
        sql += " AND DATE(requested_at)<=%s"
        args.append(date_to)
    sql += " ORDER BY requested_at DESC"
    rides     = q(sql, args)
    locations = q("SELECT * FROM Locations WHERE is_active=1 ORDER BY location_name")
    return render_template('admin/rides.html', rides=rides, locations=locations,
                           search=search, status=status, loc_id=loc_id,
                           date_from=date_from, date_to=date_to)

@app.route('/admin/rides/<int:ride_id>/cancel', methods=['POST'])
@auth('admin')
def admin_cancel_ride(ride_id):
    cur = mysql.connection.cursor()
    cur.execute("CALL sp_cancel_ride(%s, @success, @message)", (ride_id,))
    cur.fetchall()
    cur.close()
    cur2 = mysql.connection.cursor()
    cur2.execute("SELECT @success, @message")
    row = cur2.fetchone()
    cur2.close()
    if row and row.get('@success'):
        flash(f'Ride #{ride_id} cancelled.', 'info')
    else:
        flash(row.get('@message','This ride cannot be cancelled.') if row else 'This ride cannot be cancelled.', 'danger')
    return redirect(url_for('admin_rides'))

# ── Admin: Drivers ────────────────────────────────────────────
@app.route('/admin/drivers')
@auth('admin')
def admin_drivers():
    search       = request.args.get('q','')
    avail_filter = request.args.get('avail','')
    sql  = """SELECT * FROM vw_driver_stats WHERE 1=1"""
    args = []
    if search: sql += " AND (full_name LIKE %s OR vehicle_plate LIKE %s OR license_number LIKE %s)"; args += [f'%{search}%']*3
    if avail_filter == '1': sql += " AND is_available=1"
    elif avail_filter == '0': sql += " AND is_available=0"
    sql += " ORDER BY joined_at DESC"
    drivers = q(sql, args)
    return render_template('admin/drivers.html', drivers=drivers,
                           search=search, avail_filter=avail_filter)

@app.route('/admin/drivers/new', methods=['GET','POST'])
@auth('admin')
def admin_new_driver():
    if request.method == 'POST':
        fn  = request.form.get('first_name','').strip()
        ln  = request.form.get('last_name','').strip()
        ph  = request.form.get('phone','').strip()
        lic = request.form.get('license','').strip().upper()
        plt = request.form.get('plate','').strip().upper()
        vm  = request.form.get('vehicle_model','').strip()
        pw  = request.form.get('password','')
        pw2 = request.form.get('confirm_password','')
        errors = []
        if not val_name(fn):  errors.append('First name required.')
        if not val_name(ln):  errors.append('Last name required.')
        if not ph or not val_phone(ph): errors.append('Valid phone number required.')
        if not lic or not val_lic(lic): errors.append('Valid license number required.')
        if not plt or not val_plate(plt): errors.append('Vehicle plate required (4–12 alphanumeric).')
        if not pw or not val_pw(pw): errors.append('Password must be at least 6 characters.')
        if pw != pw2: errors.append('Passwords do not match.')
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('admin/driver_form.html', driver=None, form=request.form)
        try:
            m("INSERT INTO Drivers(first_name,last_name,phone_number,license_number,"
              "vehicle_plate,vehicle_model,password_hash) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (fn, ln, ph, lic, plt, vm, hash_pw(pw)))
            flash(f'Driver {fn} {ln} added successfully.', 'success')
            return redirect(url_for('admin_drivers'))
        except:
            flash('Phone number, license, or plate already registered.', 'danger')
    return render_template('admin/driver_form.html', driver=None, form={})

@app.route('/admin/drivers/<int:did>/edit', methods=['GET','POST'])
@auth('admin')
def admin_edit_driver(did):
    d = q("SELECT * FROM Drivers WHERE driver_id=%s", (did,), one=True)
    if not d:
        flash('Driver not found.', 'danger')
        return redirect(url_for('admin_drivers'))
    if request.method == 'POST':
        fn  = request.form.get('first_name','').strip()
        ln  = request.form.get('last_name','').strip()
        ph  = request.form.get('phone','').strip()
        lic = request.form.get('license','').strip().upper()
        plt = request.form.get('plate','').strip().upper()
        vm  = request.form.get('vehicle_model','').strip()
        pw  = request.form.get('new_password','')
        pw2 = request.form.get('confirm_password','')
        errors = []
        if not val_name(fn): errors.append('First name required.')
        if not val_name(ln): errors.append('Last name required.')
        if ph and not val_phone(ph): errors.append('Invalid phone number.')
        if plt and not val_plate(plt): errors.append('Invalid plate format.')
        if pw and not val_pw(pw): errors.append('Password must be at least 6 characters.')
        if pw and pw != pw2: errors.append('Passwords do not match.')
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('admin/driver_form.html', driver=d, form=request.form)
        if pw:
            m("UPDATE Drivers SET first_name=%s,last_name=%s,phone_number=%s,license_number=%s,"
              "vehicle_plate=%s,vehicle_model=%s,password_hash=%s WHERE driver_id=%s",
              (fn, ln, ph or d['phone_number'], lic or d['license_number'],
               plt or d['vehicle_plate'], vm, hash_pw(pw), did))
        else:
            m("UPDATE Drivers SET first_name=%s,last_name=%s,phone_number=%s,license_number=%s,"
              "vehicle_plate=%s,vehicle_model=%s WHERE driver_id=%s",
              (fn, ln, ph or d['phone_number'], lic or d['license_number'],
               plt or d['vehicle_plate'], vm, did))
        flash(f'Driver {fn} {ln} updated.', 'success')
        return redirect(url_for('admin_drivers'))
    return render_template('admin/driver_form.html', driver=d, form=dict(d))

@app.route('/admin/drivers/<int:did>/toggle', methods=['POST'])
@auth('admin')
def admin_toggle_driver(did):
    d = q("SELECT is_available FROM Drivers WHERE driver_id=%s", (did,), one=True)
    if d:
        m("UPDATE Drivers SET is_available=%s WHERE driver_id=%s", (0 if d['is_available'] else 1, did))
        flash('Driver availability updated.', 'info')
    return redirect(url_for('admin_drivers'))

@app.route('/admin/admins', methods=['GET', 'POST'])
@auth('admin')
def admin_admins():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        role     = request.form.get('role', 'admin').strip() or 'admin'
        pw       = request.form.get('password', '')
        pw2      = request.form.get('confirm_password', '')

        errors = []
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not email or not val_email(email):
            errors.append('Enter a valid email address.')
        if not pw or not val_pw(pw):
            errors.append('Password must be at least 6 characters.')
        if pw != pw2:
            errors.append('Passwords do not match.')
        if role not in ['admin', 'superadmin']:
            errors.append('Invalid admin role selected.')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            try:
                m("INSERT INTO Admin_Users(username,email,password_hash,role) VALUES(%s,%s,%s,%s)",
                  (username, email, hash_pw(pw), role))
                flash(f'Admin account \"{username}\" created successfully.', 'success')
                return redirect(url_for('admin_admins'))
            except Exception:
                flash('Username or email already exists.', 'danger')

    search = request.args.get('q', '')
    sql = """SELECT a.*,
        COUNT(rr.report_id) AS report_count
        FROM Admin_Users a
        LEFT JOIN Ride_Reports rr ON rr.admin_id = a.admin_id
        WHERE 1=1"""
    args = []
    if search:
        sql += " AND (a.username LIKE %s OR a.email LIKE %s OR a.role LIKE %s)"
        args += [f'%{search}%'] * 3
    sql += " GROUP BY a.admin_id ORDER BY a.created_at DESC"
    admins = q(sql, args)
    return render_template('admin/admins.html', admins=admins, search=search)

@app.route('/admin/admins/<int:aid>/edit', methods=['GET', 'POST'])
@auth('admin')
def admin_edit_admin(aid):
    admin_user = q("SELECT * FROM Admin_Users WHERE admin_id=%s", (aid,), one=True)
    if not admin_user:
        flash('Admin user not found.', 'danger')
        return redirect(url_for('admin_admins'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        role     = request.form.get('role', 'admin').strip() or 'admin'
        pw       = request.form.get('password', '')
        pw2      = request.form.get('confirm_password', '')

        errors = []
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not email or not val_email(email):
            errors.append('Enter a valid email address.')
        if role not in ['admin', 'superadmin']:
            errors.append('Invalid admin role selected.')
        if pw and not val_pw(pw):
            errors.append('Password must be at least 6 characters.')
        if pw and pw != pw2:
            errors.append('Passwords do not match.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/admin_form.html', admin_user=admin_user, form=request.form)

        try:
            if pw:
                m("UPDATE Admin_Users SET username=%s,email=%s,role=%s,password_hash=%s WHERE admin_id=%s",
                  (username, email, role, hash_pw(pw), aid))
            else:
                m("UPDATE Admin_Users SET username=%s,email=%s,role=%s WHERE admin_id=%s",
                  (username, email, role, aid))

            if aid == session.get('uid'):
                session['name'] = username

            flash(f'Admin account "{username}" updated.', 'success')
            return redirect(url_for('admin_admins'))
        except Exception:
            flash('Username or email already exists.', 'danger')

    return render_template('admin/admin_form.html', admin_user=admin_user, form=dict(admin_user))

@app.route('/admin/admins/<int:aid>/delete', methods=['POST'])
@auth('admin')
def admin_delete_admin(aid):
    if aid == session.get('uid'):
        flash('You cannot delete your own admin account while logged in.', 'danger')
        return redirect(url_for('admin_admins'))

    target = q("SELECT admin_id, username FROM Admin_Users WHERE admin_id=%s", (aid,), one=True)
    if not target:
        flash('Admin user not found.', 'danger')
        return redirect(url_for('admin_admins'))

    reports = q("SELECT COUNT(*) as c FROM Ride_Reports WHERE admin_id=%s", (aid,), one=True)
    if reports and reports['c'] > 0:
        flash('Cannot delete an admin who has generated reports.', 'danger')
        return redirect(url_for('admin_admins'))

    m("DELETE FROM Admin_Users WHERE admin_id=%s", (aid,))
    flash(f'Admin account "{target["username"]}" deleted.', 'info')
    return redirect(url_for('admin_admins'))

@app.route('/admin/drivers/<int:did>/delete', methods=['POST'])
@auth('admin')
def admin_delete_driver(did):
    active = q("SELECT COUNT(*) as c FROM Rides WHERE driver_id=%s AND ride_status IN ('ACCEPTED','IN_PROGRESS')",
               (did,), one=True)
    if active['c'] > 0:
        flash('Cannot delete a driver with active rides.', 'danger')
    else:
        m("DELETE FROM Drivers WHERE driver_id=%s", (did,))
        flash('Driver removed.', 'info')
    return redirect(url_for('admin_drivers'))

# ── Admin: Locations ─────────────────────────────────────────
@app.route('/admin/locations', methods=['GET','POST'])
@auth('admin')
def admin_locations():
    if request.method == 'POST':
        name = request.form.get('location_name','').strip()
        zone = request.form.get('area_zone','CBD')
        desc = request.form.get('description','').strip()
        if len(name) < 3:
            flash('Location name must be at least 3 characters.', 'danger')
        else:
            try:
                m("INSERT INTO Locations(location_name,area_zone,description) VALUES(%s,%s,%s)", (name,zone,desc))
                flash(f'Location "{name}" added.', 'success')
            except:
                flash('A location with that name already exists.', 'danger')
        return redirect(url_for('admin_locations'))
    search = request.args.get('q','')
    zone   = request.args.get('zone','')
    sql    = """SELECT l.*,
        (SELECT COUNT(*) FROM Rides WHERE pickup_location_id=l.location_id OR dropoff_location_id=l.location_id) as ride_count
        FROM Locations l WHERE 1=1"""
    args   = []
    if search: sql += " AND l.location_name LIKE %s"; args.append(f'%{search}%')
    if zone:   sql += " AND l.area_zone=%s"; args.append(zone)
    sql += " ORDER BY l.area_zone, l.location_name"
    locations = q(sql, args)
    return render_template('admin/locations.html', locations=locations, search=search, zone=zone)

@app.route('/admin/locations/<int:lid>/edit', methods=['GET','POST'])
@auth('admin')
def admin_edit_location(lid):
    loc = q("SELECT *, total_rides AS ride_count FROM vw_location_demand WHERE location_id=%s", (lid,), one=True)
    if not loc:
        flash('Location not found.', 'danger')
        return redirect(url_for('admin_locations'))
    if request.method == 'POST':
        name = request.form.get('location_name','').strip()
        zone = request.form.get('area_zone','CBD')
        desc = request.form.get('description','').strip()
        if len(name) < 3:
            flash('Location name must be at least 3 characters.', 'danger')
        else:
            m("UPDATE Locations SET location_name=%s,area_zone=%s,description=%s WHERE location_id=%s",
              (name, zone, desc, lid))
            flash(f'Location updated to "{name}".', 'success')
            return redirect(url_for('admin_locations'))
    return render_template('admin/location_form.html', loc=loc)

@app.route('/admin/locations/<int:lid>/toggle', methods=['POST'])
@auth('admin')
def admin_toggle_location(lid):
    loc = q("SELECT is_active FROM Locations WHERE location_id=%s", (lid,), one=True)
    if loc:
        m("UPDATE Locations SET is_active=%s WHERE location_id=%s", (0 if loc['is_active'] else 1, lid))
        flash('Location status updated.', 'info')
    return redirect(url_for('admin_locations'))

# ── Admin: Reports ────────────────────────────────────────────
@app.route('/admin/reports', methods=['GET','POST'])
@auth('admin')
def admin_reports():
    today = datetime.date.today().isoformat()
    if request.method == 'POST':
        rdate = request.form.get('report_date','')
        rtype = request.form.get('report_type','Daily Summary')
        notes = request.form.get('notes','').strip()
        lid   = request.form.get('top_location_id','') or None
        if not rdate:
            flash('Please select a report date.', 'danger')
        else:
            totals = q("SELECT COUNT(*) as c, COALESCE(SUM(fare_amount),0) as rev "
                       "FROM Rides WHERE DATE(requested_at)=%s AND ride_status='COMPLETED'",
                       (rdate,), one=True)
            if not lid:
                top = q("SELECT pickup_location_id FROM Rides WHERE DATE(requested_at)=%s "
                        "GROUP BY pickup_location_id ORDER BY COUNT(*) DESC LIMIT 1", (rdate,), one=True)
                lid = top['pickup_location_id'] if top else None
            m("INSERT INTO Ride_Reports(admin_id,report_type,report_date,total_rides,total_revenue,"
              "top_location_id,notes) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (session['uid'], rtype, rdate, totals['c'], totals['rev'], lid, notes))
            flash(f'{rtype} report for {rdate} generated.', 'success')
        return redirect(url_for('admin_reports'))
    search      = request.args.get('q','')
    type_filter = request.args.get('type_filter','')
    sql  = """SELECT rr.*, a.username, l.location_name AS top_location_name
        FROM Ride_Reports rr
        JOIN Admin_Users a ON rr.admin_id=a.admin_id
        LEFT JOIN Locations l ON rr.top_location_id=l.location_id WHERE 1=1"""
    args = []
    if search:      sql += " AND (rr.report_type LIKE %s OR rr.notes LIKE %s)"; args += [f'%{search}%']*2
    if type_filter: sql += " AND rr.report_type=%s"; args.append(type_filter)
    sql += " ORDER BY rr.generated_at DESC"
    reports   = q(sql, args)
    daily     = q("SELECT ride_date AS day, total_rides AS rides, revenue FROM vw_daily_revenue ORDER BY ride_date DESC LIMIT 14")
    locations = q("SELECT * FROM Locations WHERE is_active=1 ORDER BY location_name")
    return render_template('admin/reports.html', reports=reports, daily=daily,
                           locations=locations, today=today,
                           search=search, type_filter=type_filter)

@app.route('/admin/reports/<int:rid>/delete', methods=['POST'])
@auth('admin')
def admin_delete_report(rid):
    m("DELETE FROM Ride_Reports WHERE report_id=%s", (rid,))
    flash('Report deleted.', 'info')
    return redirect(url_for('admin_reports'))


@app.route('/admin/reports/<int:rid>/pdf')
@auth('admin')
def admin_report_pdf(rid):
    report = q("""SELECT rr.*, a.username, l.location_name AS top_location_name
                  FROM Ride_Reports rr
                  JOIN Admin_Users a ON rr.admin_id = a.admin_id
                  LEFT JOIN Locations l ON rr.top_location_id = l.location_id
                  WHERE rr.report_id=%s""", (rid,), one=True)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('admin_reports'))

    rides = q("""SELECT passenger_name, passenger_phone, pickup_name, dropoff_name,
                        COALESCE(driver_name, 'Unassigned') AS driver_name,
                        ride_status, fare_amount
                 FROM vw_rides_full
                 WHERE DATE(requested_at)=%s
                 ORDER BY requested_at DESC
                 LIMIT 20""", (report['report_date'],))

    lines = [
        f"Report type: {report['report_type']}",
        f"Report date: {report['report_date']}",
        f"Generated at: {report['generated_at'].strftime('%Y-%m-%d %H:%M') if report['generated_at'] else ''}",
        f"Prepared by: {report['username']}",
        f"Total rides: {report['total_rides']}",
        f"Total revenue: M {float(report['total_revenue'] or 0):.2f}",
        f"Top location: {report['top_location_name'] or 'None'}",
        f"Notes: {report['notes'] or 'None'}",
        "",
        "Ride details (up to 20 records for the report date):"
    ]

    if rides:
        for idx, ride in enumerate(rides, start=1):
            lines.append(
                f"{idx}. {ride['passenger_name']} | {ride['pickup_name']} -> {ride['dropoff_name']} | "
                f"Driver: {ride['driver_name']} | Status: {ride['ride_status']} | "
                f"Fare: M {float(ride['fare_amount'] or 0):.2f}"
            )
    else:
        lines.append("No ride records found for this report date.")

    pdf_bytes = build_simple_pdf(
        f"Lipalangoang Report #{report['report_id']}",
        lines
    )
    safe_type = re.sub(r'[^A-Za-z0-9]+', '_', report['report_type']).strip('_') or 'report'
    filename = f"{safe_type}_{report['report_date']}_report_{report['report_id']}.pdf"

    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=\"{filename}\"'
    return response

@app.route('/api/fare')
def api_fare():
    """Return the fixed fare for two locations. Called by JS on the booking form."""
    pickup_id  = request.args.get('pickup', type=int)
    dropoff_id = request.args.get('dropoff', type=int)
    if not pickup_id or not dropoff_id:
        return jsonify({'fare': None})
    fare = get_fare(pickup_id, dropoff_id)
    return jsonify({'fare': fare})

if __name__ == '__main__':
    app.run(debug=True, port=5000)

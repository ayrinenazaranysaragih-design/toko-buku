import os, sqlite3, uuid
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, abort)

app = Flask(__name__)
app.secret_key = "Ayrine-Nazarany-Saragih14"   # ganti sebelum dipakai sungguhan
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "toko.db")
UPLOAD = os.path.join(BASE, "static", "uploads")
ADMIN_USER, ADMIN_PASS = "ayrine", "ayrine14"   # ganti password ini!
ALLOWED = {"png", "jpg", "jpeg", "webp", "gif"}


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS books(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        author TEXT NOT NULL, price INTEGER NOT NULL, stock INTEGER NOT NULL,
        cover TEXT, description TEXT);
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, customer TEXT NOT NULL,
        phone TEXT NOT NULL, address TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Lunas',
        created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL, qty INTEGER NOT NULL, price INTEGER NOT NULL);""")
    if c.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
        c.executemany("INSERT INTO books(title,author,price,stock,description) VALUES(?,?,?,?,?)", [
            ("Petualangan di Negeri Awan", "Mira Lestari", 65000, 12, "Cerita hangat tentang anak kecil yang menemukan pintu rahasia di langit."),
            ("Resep Kue Si Kelinci", "Dapur Bunga", 80000, 8, "Resep kue manis yang gampang dibuat di rumah."),
            ("Catatan Kucing Malas", "Rafi Pratama", 55000, 20, "Kumpulan cerita lucu tentang kucing yang hobi rebahan."),
        ])
    c.commit(); c.close()

@app.template_filter("rp")
def rupiah(n):
    return "Rp " + f"{int(n):,}".replace(",", ".")

def save_cover(file):
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in ALLOWED:
            name = uuid.uuid4().hex + "." + ext
            file.save(os.path.join(UPLOAD, name))
            return name
    return None

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*a, **k)
    return w


# ---------- halaman pembeli ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    books = db().execute("SELECT * FROM books WHERE title LIKE ? OR author LIKE ? ORDER BY id DESC",
                         (f"%{q}%", f"%{q}%")).fetchall()
    return render_template("index.html", books=books, q=q)

@app.route("/buku/<int:id>")
def detail(id):
    book = db().execute("SELECT * FROM books WHERE id=?", (id,)).fetchone() or abort(404)
    return render_template("detail.html", book=book)

@app.context_processor
def inject_cart():
    return {"cart_count": sum(session.get("cart", {}).values())}

def cart_items():
    cart, items = session.get("cart", {}), []
    for bid, qty in cart.items():
        b = db().execute("SELECT * FROM books WHERE id=?", (int(bid),)).fetchone()
        if b:
            items.append({"book": b, "qty": qty, "sub": qty * b["price"]})
    return items

@app.route("/keranjang/tambah/<int:id>", methods=["POST"])
def cart_add(id):
    book = db().execute("SELECT * FROM books WHERE id=?", (id,)).fetchone() or abort(404)
    cart = session.get("cart", {})
    qty = cart.get(str(id), 0) + max(1, request.form.get("qty", type=int, default=1))
    if qty > book["stock"]:
        flash(f"Stok '{book['title']}' tinggal {book['stock']}.", "err")
        return redirect(url_for("detail", id=id))
    cart[str(id)] = qty
    session["cart"] = cart
    flash("Masuk keranjang! 🛒", "ok")
    return redirect(url_for("cart"))

@app.route("/keranjang/hapus/<int:id>", methods=["POST"])
def cart_remove(id):
    cart = session.get("cart", {})
    cart.pop(str(id), None)
    session["cart"] = cart
    return redirect(url_for("cart"))

@app.route("/keranjang")
def cart():
    items = cart_items()
    return render_template("cart.html", items=items, total=sum(i["sub"] for i in items))

@app.route("/checkout", methods=["POST"])
def checkout():
    items = cart_items()
    f = request.form
    if not items:
        return redirect(url_for("cart"))
    if not (f["customer"].strip() and f["phone"].strip() and f["address"].strip()):
        flash("Lengkapi nama, nomor HP, dan alamat ya.", "err")
        return redirect(url_for("cart"))
    for i in items:
        if i["qty"] > i["book"]["stock"]:
            flash(f"Stok '{i['book']['title']}' tidak cukup.", "err")
            return redirect(url_for("cart"))
    now = datetime.now()
    code = "BK" + now.strftime("%y%m%d") + uuid.uuid4().hex[:4].upper()
    cur = db().execute("INSERT INTO orders(code,customer,phone,address,status,created) VALUES(?,?,?,?,?,?)",
                       (code, f["customer"].strip(), f["phone"].strip(), f["address"].strip(), "Lunas",
                        now.strftime("%Y-%m-%d %H:%M")))
    for i in items:
        db().execute("INSERT INTO order_items(order_id,book_id,qty,price) VALUES(?,?,?,?)",
                     (cur.lastrowid, i["book"]["id"], i["qty"], i["book"]["price"]))
        db().execute("UPDATE books SET stock=stock-? WHERE id=?", (i["qty"], i["book"]["id"]))
    db().commit()
    session.pop("cart", None)
    return redirect(url_for("struk", code=code))

ORDERS_SQL = """SELECT o.*, COALESCE(SUM(i.qty*i.price),0) AS total, COALESCE(SUM(i.qty),0) AS jumlah
                FROM orders o LEFT JOIN order_items i ON i.order_id=o.id {where} GROUP BY o.id ORDER BY o.id DESC"""

def get_order(**kw):
    col, val = next(iter(kw.items()))
    order = db().execute(ORDERS_SQL.format(where=f"WHERE o.{col}=?"), (val,)).fetchone() or abort(404)
    lines = db().execute("""SELECT i.*, b.title, b.author FROM order_items i
                            JOIN books b ON b.id=i.book_id WHERE i.order_id=?""", (order["id"],)).fetchall()
    return order, lines

@app.route("/struk/<code>")
def struk(code):
    order, lines = get_order(code=code)
    return render_template("struk.html", o=order, lines=lines)


# ---------- admin ----------
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin"] = True
            return redirect(url_for("dashboard"))
        flash("Username atau password salah.", "err")
    return render_template("login.html")

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def dashboard():
    orders = db().execute(ORDERS_SQL.format(where="")).fetchall()
    paid = [o for o in orders if o["status"] == "Lunas"]
    stats = {"omzet": sum(o["total"] for o in paid), "terjual": sum(o["jumlah"] for o in paid),
             "transaksi": len(paid), "pembeli": len({o["phone"] for o in paid})}
    return render_template("dashboard.html", orders=orders, stats=stats)


@app.route("/admin/buku")
@admin_required
def admin_books():
    books = db().execute("SELECT * FROM books ORDER BY id DESC").fetchall()
    return render_template("admin_books.html", books=books)

@app.route("/admin/buku/tambah", methods=["GET", "POST"])
@app.route("/admin/buku/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def book_form(id=None):
    book = None
    if id:
        book = db().execute("SELECT * FROM books WHERE id=?", (id,)).fetchone() or abort(404)
    if request.method == "POST":
        f = request.form
        cover = save_cover(request.files.get("cover")) or (book["cover"] if book else None)
        vals = (f["title"], f["author"], int(f["price"]), int(f["stock"]), cover, f["description"])
        if book:
            db().execute("UPDATE books SET title=?,author=?,price=?,stock=?,cover=?,description=? WHERE id=?", vals + (id,))
        else:
            db().execute("INSERT INTO books(title,author,price,stock,cover,description) VALUES(?,?,?,?,?,?)", vals)
        db().commit()
        flash("Buku tersimpan!", "ok")
        return redirect(url_for("admin_books"))
    return render_template("book_form.html", book=book)

@app.route("/admin/buku/<int:id>/hapus", methods=["POST"])
@admin_required
def book_delete(id):
    if db().execute("SELECT 1 FROM order_items WHERE book_id=?", (id,)).fetchone():
        flash("Buku ini sudah punya riwayat penjualan, jadi tidak bisa dihapus. Set stok ke 0 saja.", "err")
    else:
        db().execute("DELETE FROM books WHERE id=?", (id,)); db().commit()
        flash("Buku dihapus.", "ok")
    return redirect(url_for("admin_books"))

def restock(lines, sign):   # sign=+1 kembalikan stok, -1 kurangi stok
    for l in lines:
        db().execute("UPDATE books SET stock=stock+? WHERE id=?", (sign * l["qty"], l["book_id"]))

@app.route("/admin/pesanan/<int:id>", methods=["GET", "POST"])
@admin_required
def order_detail(id):
    order, lines = get_order(id=id)
    if request.method == "POST":
        f, status = request.form, request.form["status"]
        if order["status"] == "Lunas" and status == "Dibatalkan":
            restock(lines, +1)
        elif order["status"] == "Dibatalkan" and status == "Lunas":
            for l in lines:
                st = db().execute("SELECT stock FROM books WHERE id=?", (l["book_id"],)).fetchone()["stock"]
                if st < l["qty"]:
                    flash(f"Stok '{l['title']}' tidak cukup untuk mengaktifkan lagi.", "err")
                    return redirect(url_for("order_detail", id=id))
            restock(lines, -1)
        db().execute("UPDATE orders SET customer=?,phone=?,address=?,status=? WHERE id=?",
                     (f["customer"], f["phone"], f["address"], status, id))
        db().commit()
        flash("Pesanan diperbarui.", "ok")
        return redirect(url_for("order_detail", id=id))
    return render_template("order_detail.html", o=order, lines=lines)

@app.route("/admin/pesanan/<int:id>/hapus", methods=["POST"])
@admin_required
def order_delete(id):
    order, lines = get_order(id=id)
    if order["status"] == "Lunas":
        restock(lines, +1)
    db().execute("DELETE FROM order_items WHERE order_id=?", (id,))
    db().execute("DELETE FROM orders WHERE id=?", (id,))
    db().commit()
    flash("Pesanan dihapus.", "ok")
    return redirect(url_for("dashboard"))


init_db()
if __name__ == "__main__":
    app.run(debug=True)

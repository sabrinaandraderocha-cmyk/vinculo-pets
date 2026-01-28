from flask import (
    Flask, render_template, request, redirect,
    url_for, Response, abort, session
)
import sqlite3
from datetime import datetime, timedelta
import random
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")

# Para deploy: use instance/ para organizar o banco
os.makedirs("instance", exist_ok=True)
DB_PATH = os.path.join("instance", "database.db")

# =========================
# DB helpers
# =========================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def table_info(conn, table_name):
    return conn.execute(f"PRAGMA table_info({table_name})").fetchall()

def has_column(conn, table, column):
    return any(c["name"] == column for c in table_info(conn, table))

def add_column_if_missing(conn, table, column_def, column_name):
    if not has_column(conn, table, column_name):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")

def init_db():
    conn = get_db_connection()

    # USERS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # PETS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            nome TEXT,
            especie TEXT,
            nascimento TEXT,
            obs TEXT,
            tutor TEXT,
            resp1_tipo TEXT,
            resp1_nome TEXT,
            resp2_tipo TEXT,
            resp2_nome TEXT,
            musica_preferida TEXT,
            vet_preferido TEXT,
            motivo_nome TEXT,
            alimentos_preferidos TEXT,
            alimentos_proibidos TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # MIGRATIONS PETS
    columns_pets = [
        ("user_id INTEGER", "user_id"), ("tutor TEXT", "tutor"),
        ("resp1_tipo TEXT", "resp1_tipo"), ("resp1_nome TEXT", "resp1_nome"),
        ("resp2_tipo TEXT", "resp2_tipo"), ("resp2_nome TEXT", "resp2_nome"),
        ("musica_preferida TEXT", "musica_preferida"), ("vet_preferido TEXT", "vet_preferido"),
        ("motivo_nome TEXT", "motivo_nome"), ("alimentos_preferidos TEXT", "alimentos_preferidos"),
        ("alimentos_proibidos TEXT", "alimentos_proibidos")
    ]
    for col_def, col_name in columns_pets:
        add_column_if_missing(conn, "pets", col_def, col_name)

    # REGISTROS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER,
            data TEXT,
            nota TEXT,
            humor TEXT,
            categoria TEXT,
            personalidade_hoje TEXT,
            latindo INTEGER DEFAULT 0,
            mordeu_carteiro INTEGER DEFAULT 0,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "registros", "categoria TEXT", "categoria")
    add_column_if_missing(conn, "registros", "personalidade_hoje TEXT", "personalidade_hoje")
    add_column_if_missing(conn, "registros", "latindo INTEGER DEFAULT 0", "latindo")
    add_column_if_missing(conn, "registros", "mordeu_carteiro INTEGER DEFAULT 0", "mordeu_carteiro")

    # AGENDA
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER,
            tarefa TEXT,
            data_prevista TEXT,
            concluida INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "agenda", "created_at TEXT", "created_at")

    # EVENTOS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER,
            tipo TEXT,
            data_evento TEXT,
            detalhes TEXT,
            criado_em TEXT,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "eventos", "criado_em TEXT", "criado_em")

    conn.commit()
    conn.close()

# =========================
# Auth & Helpers
# =========================
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def current_user_id():
    return session.get("user_id")

def fetch_pet_or_404(conn, pet_id):
    pet = conn.execute(
        "SELECT * FROM pets WHERE id = ? AND user_id = ?",
        (pet_id, current_user_id()),
    ).fetchone()
    if not pet:
        abort(404)
    return pet

def get_responsaveis(pet_row):
    parts = []
    t1, n1 = (pet_row["resp1_tipo"] or "").strip(), (pet_row["resp1_nome"] or "").strip()
    t2, n2 = (pet_row["resp2_tipo"] or "").strip(), (pet_row["resp2_nome"] or "").strip()
    if t1 and n1: parts.append(f"{t1}: {n1}")
    if t2 and n2: parts.append(f"{t2}: {n2}")
    if not parts and (pet_row["tutor"] or "").strip():
        parts.append(f"Tutor: {pet_row['tutor'].strip()}")
    return parts

# =========================
# Business Logic
# =========================
CURIOSIDADES = {
    "gato": ["Gatos costumam beber pouca água. Fontes ajudam.", "Ronronar pode ser conforto ou estresse.", "Arranhar é comunicação e autocuidado."],
    "cão": ["Passeios olfativos relaxam mais que andar rápido.", "Mudanças de sono valem registro.", "Rotina traz segurança."],
    "outro": ["Animais pequenos escondem sintomas.", "Ambiente rico reduz estresse.", "Mudanças sutis são importantes."]
}

def pick_curiosidade(especie):
    e = (especie or "").lower()
    if "gat" in e: pool = CURIOSIDADES["gato"]
    elif any(x in e for x in ["cã", "cao", "dog"]): pool = CURIOSIDADES["cão"]
    else: pool = CURIOSIDADES["outro"]
    return random.choice(pool)

def compute_wellbeing_summary(registros):
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    counts, total = {}, 0
    for r in registros:
        try:
            dt = datetime.strptime(r["data"], "%d/%m/%Y %H:%M")
            if dt >= cutoff:
                total += 1
                h = (r["humor"] or "Sem rótulo").strip()
                counts[h] = counts.get(h, 0) + 1
        except: continue
    top_humor = max(counts, key=counts.get) if counts else None
    return {"total_7d": total, "top_humor": top_humor, "top_count": counts.get(top_humor, 0)}

# =========================
# ROUTES
# =========================
@app.route("/signup", methods=("GET", "POST"))
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            return render_template("signup.html", error="Preencha e-mail e senha.")
        conn = get_db_connection()
        exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            conn.close()
            return render_template("signup.html", error="E-mail já existe.")
        pw_hash = generate_password_hash(password)
        created_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        conn.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)", (email, pw_hash, created_at))
        conn.commit()
        user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("signup.html")

@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Credenciais inválidas.")
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    pets = conn.execute("SELECT * FROM pets WHERE user_id = ? ORDER BY id DESC", (current_user_id(),)).fetchall()
    conn.close()
    curiosidade_home = pick_curiosidade(pets[0]["especie"] if pets else "outro")
    return render_template("index.html", pets=pets, curiosidade_home=curiosidade_home)

@app.route("/cadastrar", methods=("GET", "POST"))
@login_required
def cadastrar():
    if request.method == "POST":
        f = request.form
        nome, especie = f.get("nome", "").strip(), f.get("especie", "").strip()
        if not nome or not especie:
            return render_template("cadastro.html", error="Nome e espécie obrigatórios.")
        conn = get_db_connection()
        conn.execute("""INSERT INTO pets (user_id, nome, especie, nascimento, obs, tutor, resp1_tipo, resp1_nome, 
                        resp2_tipo, resp2_nome, musica_preferida, vet_preferido, motivo_nome, 
                        alimentos_preferidos, alimentos_proibidos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (current_user_id(), nome, especie, f.get("nascimento"), f.get("obs"), f.get("resp1_nome"),
                      f.get("resp1_tipo"), f.get("resp1_nome"), f.get("resp2_tipo"), f.get("resp2_nome"),
                      f.get("musica_preferida"), f.get("vet_preferido"), f.get("motivo_nome"),
                      f.get("alimentos_preferidos"), f.get("alimentos_proibidos")))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("cadastro.html")

@app.route("/pet/<int:pet_id>")
@login_required
def detalhes_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)
    registros = conn.execute("SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC", (pet_id,)).fetchall()
    agenda_pend = conn.execute("SELECT * FROM agenda WHERE pet_id = ? AND concluida = 0 ORDER BY data_prevista ASC", (pet_id,)).fetchall()
    eventos = conn.execute("SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC", (pet_id,)).fetchall()
    summary = compute_wellbeing_summary(registros)
    curiosidade = pick_curiosidade(pet["especie"])
    responsaveis = get_responsaveis(pet)
    conn.close()
    return render_template("detalhes.html", pet=pet, registros=registros, agenda_pend=agenda_pend, 
                           eventos=eventos, summary=summary, curiosidade=curiosidade, responsaveis=responsaveis)

@app.route("/pet/<int:pet_id>/anotar", methods=("POST",))
@login_required
def anotar(pet_id):
    f = request.form
    conn = get_db_connection()
    fetch_pet_or_404(conn, pet_id)
    conn.execute("""INSERT INTO registros (pet_id, data, nota, humor, categoria, personalidade_hoje, latindo, mordeu_carteiro)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                 (pet_id, datetime.now().strftime("%d/%m/%Y %H:%M"), f.get("nota"), f.get("humor"), 
                  f.get("categoria"), f.get("personalidade_hoje"), 1 if f.get("latindo")=="on" else 0, 1 if f.get("mordeu_carteiro")=="on" else 0))
    conn.commit()
    conn.close()
    return redirect(url_for("detalhes_pet", pet_id=pet_id))

@app.route("/pet/<int:pet_id>/agenda/add", methods=("POST",))
@login_required
def agenda_add(pet_id):
    tarefa = request.form.get("tarefa")
    if tarefa:
        conn = get_db_connection()
        fetch_pet_or_404(conn, pet_id)
        conn.execute("INSERT INTO agenda (pet_id, tarefa, data_prevista, created_at) VALUES (?, ?, ?, ?)",
                     (pet_id, tarefa, request.form.get("data_prevista"), datetime.now().strftime("%d/%m/%Y %H:%M")))
        conn.commit()
        conn.close()
    return redirect(url_for("detalhes_pet", pet_id=pet_id))

@app.route("/agenda/<int:agenda_id>/done", methods=("POST",))
@login_required
def agenda_done(agenda_id):
    conn = get_db_connection()
    item = conn.execute("SELECT pet_id FROM agenda WHERE id = ?", (agenda_id,)).fetchone()
    if item:
        fetch_pet_or_404(conn, item["pet_id"])
        conn.execute("UPDATE agenda SET concluida = 1 WHERE id = ?", (agenda_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("detalhes_pet", pet_id=item["pet_id"]))

# =========================
# Run Initialization & Server
# =========================

# CRÍTICO: Executa a criação do banco de dados ao importar o arquivo
init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

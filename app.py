from flask import (
    Flask, render_template, request, redirect,
    url_for, Response, abort, session, flash
)
import sqlite3
from datetime import datetime, timedelta
import random
import string
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
# Chave secreta segura
app.secret_key = os.getenv("SECRET_KEY", "minha-chave-secreta-super-segura")

os.makedirs("instance", exist_ok=True)
DB_PATH = os.path.join("instance", "database.db")

# --- Banco de Dados ---
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
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass

def init_db():
    conn = get_db_connection()
    
    # Usuários
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT,
            family_id TEXT
        )
    """)
    add_column_if_missing(conn, "users", "family_id TEXT", "family_id")

    # Pets
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            nome TEXT, especie TEXT, nascimento TEXT, obs TEXT,
            tutor TEXT,
            resp1_tipo TEXT, resp1_nome TEXT,
            resp2_tipo TEXT, resp2_nome TEXT,
            musica_preferida TEXT, vet_preferido TEXT, motivo_nome TEXT,
            alimentos_preferidos TEXT, alimentos_proibidos TEXT,
            quase_chamou TEXT, como_conhecemos TEXT, atividade_preferida TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # Adicionando colunas novas se não existirem
    cols = [
        ("user_id INTEGER", "user_id"), ("tutor TEXT", "tutor"),
        ("resp1_tipo TEXT", "resp1_tipo"), ("resp1_nome TEXT", "resp1_nome"),
        ("resp2_tipo TEXT", "resp2_tipo"), ("resp2_nome TEXT", "resp2_nome"),
        ("musica_preferida TEXT", "musica_preferida"),
        ("vet_preferido TEXT", "vet_preferido"), 
        ("motivo_nome TEXT", "motivo_nome"),
        ("alimentos_preferidos TEXT", "alimentos_preferidos"),
        ("alimentos_proibidos TEXT", "alimentos_proibidos"),
        # Novos campos divertidos:
        ("quase_chamou TEXT", "quase_chamou"),
        ("como_conhecemos TEXT", "como_conhecemos"),
        ("atividade_preferida TEXT", "atividade_preferida")
    ]
    for col_def, col_name in cols:
        add_column_if_missing(conn, "pets", col_def, col_name)

    # Tabelas auxiliares
    conn.execute("""CREATE TABLE IF NOT EXISTS registros (id INTEGER PRIMARY KEY AUTOINCREMENT, pet_id INTEGER, data TEXT, nota TEXT, humor TEXT, categoria TEXT, personalidade_hoje TEXT, latindo INTEGER DEFAULT 0, mordeu_carteiro INTEGER DEFAULT 0, FOREIGN KEY (pet_id) REFERENCES pets (id))""")
    add_column_if_missing(conn, "registros", "categoria TEXT", "categoria")
    add_column_if_missing(conn, "registros", "personalidade_hoje TEXT", "personalidade_hoje")
    add_column_if_missing(conn, "registros", "latindo INTEGER DEFAULT 0", "latindo")
    add_column_if_missing(conn, "registros", "mordeu_carteiro INTEGER DEFAULT 0", "mordeu_carteiro")

    conn.execute("""CREATE TABLE IF NOT EXISTS agenda (id INTEGER PRIMARY KEY AUTOINCREMENT, pet_id INTEGER, tarefa TEXT, data_prevista TEXT, concluida INTEGER DEFAULT 0, created_at TEXT, FOREIGN KEY (pet_id) REFERENCES pets (id))""")
    add_column_if_missing(conn, "agenda", "created_at TEXT", "created_at")

    conn.execute("""CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, pet_id INTEGER, tipo TEXT, data_evento TEXT, detalhes TEXT, criado_em TEXT, FOREIGN KEY (pet_id) REFERENCES pets (id))""")
    add_column_if_missing(conn, "eventos", "criado_em TEXT", "criado_em")

    conn.commit()
    conn.close()

init_db()

# --- Funções Auxiliares ---
def gerar_codigo_familia():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=6))

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Por favor, faça login.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def current_user_id(): return session.get("user_id")

def fetch_pet_or_404(conn, pet_id):
    user_id = current_user_id()
    user = conn.execute("SELECT family_id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or not user["family_id"]:
        pet = conn.execute("SELECT * FROM pets WHERE id = ? AND user_id = ?", (pet_id, user_id)).fetchone()
    else:
        membros = conn.execute("SELECT id FROM users WHERE family_id = ?", (user["family_id"],)).fetchall()
        ids = [str(m["id"]) for m in membros]
        pet = conn.execute(f"SELECT * FROM pets WHERE id = ? AND user_id IN ({','.join(ids)})", (pet_id,)).fetchone()
    if not pet: abort(404)
    return pet

def get_responsaveis(pet_row):
    parts = []
    t1, n1 = (pet_row["resp1_tipo"] or ""), (pet_row["resp1_nome"] or "")
    t2, n2 = (pet_row["resp2_tipo"] or ""), (pet_row["resp2_nome"] or "")
    if t1 and n1: parts.append(f"{t1}: {n1}")
    if t2 and n2: parts.append(f"{t2}: {n2}")
    if not parts and pet_row["tutor"]: parts.append(f"Tutor: {pet_row['tutor']}")
    return parts

# --- Rotas ---
@app.route("/signup", methods=("GET", "POST"))
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        code = request.form.get("invite_code", "").strip().upper()
        
        conn = get_db_connection()
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            conn.close()
            flash("E-mail já existe.", "warning")
            return redirect(url_for("login"))
        
        fam_id = gerar_codigo_familia()
        if code:
            fam = conn.execute("SELECT family_id FROM users WHERE family_id=?", (code,)).fetchone()
            if fam: fam_id = fam["family_id"]
        
        conn.execute("INSERT INTO users (email, password_hash, created_at, family_id) VALUES (?, ?, ?, ?)",
                     (email, generate_password_hash(password), datetime.now().strftime("%d/%m"), fam_id))
        conn.commit()
        user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("signup.html")

@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        
        if not user or not check_password_hash(user["password_hash"], pw):
            conn.close()
            flash("Dados incorretos.", "error")
            return redirect(url_for("login"))
        
        if not user["family_id"]: # Autocura
            conn.execute("UPDATE users SET family_id=? WHERE id=?", (gerar_codigo_familia(), user["id"]))
            conn.commit()
            
        conn.close()
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
    user = conn.execute("SELECT family_id FROM users WHERE id=?", (current_user_id(),)).fetchone()
    pets = []
    my_code = user["family_id"] if user else ""
    
    if my_code:
        membros = conn.execute("SELECT id FROM users WHERE family_id=?", (my_code,)).fetchall()
        ids = [str(m["id"]) for m in membros]
        pets = conn.execute(f"SELECT * FROM pets WHERE user_id IN ({','.join(ids)}) ORDER BY id DESC").fetchall()
    
    conn.close()
    return render_template("index.html", pets=pets, my_code=my_code, curiosidade_home="Pets enriquecem a alma.")

@app.route("/cadastrar", methods=("GET", "POST"))
@login_required
def cadastrar():
    if request.method == "POST":
        f = request.form
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO pets (
                user_id, nome, especie, nascimento, obs, 
                resp1_tipo, resp1_nome, resp2_tipo, resp2_nome,
                musica_preferida, vet_preferido, motivo_nome,
                alimentos_preferidos, alimentos_proibidos,
                quase_chamou, como_conhecemos, atividade_preferida
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            current_user_id(), f.get("nome"), f.get("especie"), f.get("nascimento"), f.get("obs"),
            f.get("resp1_tipo"), f.get("resp1_nome"), f.get("resp2_tipo"), f.get("resp2_nome"),
            f.get("musica_preferida"), f.get("vet_preferido"), f.get("motivo_nome"),
            f.get("alimentos_preferidos"), f.get("alimentos_proibidos"),
            f.get("quase_chamou"), f.get("como_conhecemos"), f.get("atividade_preferida")
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("cadastro.html")

@app.route("/pet/<int:pet_id>/editar", methods=("GET", "POST"))
@login_required
def editar_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)
    if request.method == "POST":
        f = request.form
        conn.execute("""
            UPDATE pets SET nome=?, especie=?, nascimento=?, obs=?,
            resp1_tipo=?, resp1_nome=?, resp2_tipo=?, resp2_nome=?,
            musica_preferida=?, vet_preferido=?, motivo_nome=?,
            alimentos_preferidos=?, alimentos_proibidos=?,
            quase_chamou=?, como_conhecemos=?, atividade_preferida=?
            WHERE id=?
        """, (
            f.get("nome"), f.get("especie"), f.get("nascimento"), f.get("obs"),
            f.get("resp1_tipo"), f.get("resp1_nome"), f.get("resp2_tipo"), f.get("resp2_nome"),
            f.get("musica_preferida"), f.get("vet_preferido"), f.get("motivo_nome"),
            f.get("alimentos_preferidos"), f.get("alimentos_proibidos"),
            f.get("quase_chamou"), f.get("como_conhecemos"), f.get("atividade_preferida"),
            pet_id
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("detalhes_pet", pet_id=pet_id))
    conn.close()
    return render_template("cadastro.html", pet=pet, edit_mode=True)

# Demais rotas (detalhes, anotar, etc) podem ser copiadas da versão anterior ou mantidas
# Apenas certifique-se de importar e rodar o app.
@app.route("/pet/<int:pet_id>")
@login_required
def detalhes_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)
    registros = conn.execute("SELECT * FROM registros WHERE pet_id=? ORDER BY id DESC", (pet_id,)).fetchall()
    eventos = conn.execute("SELECT * FROM eventos WHERE pet_id=? ORDER BY id DESC", (pet_id,)).fetchall()
    conn.close()
    return render_template("detalhes.html", pet=pet, registros=registros, eventos=eventos, summary={}, responsaveis=get_responsaveis(pet), agenda_pend=[])

@app.route("/curiosidades")
def curiosidades(): return render_template("curiosidades.html", curiosidades={})
@app.route("/pet/<int:pet_id>/eventos")
def eventos_pet(pet_id): return redirect(url_for("detalhes_pet", pet_id=pet_id))
@app.route("/pet/<int:pet_id>/modo-vet")
def modo_vet(pet_id): return redirect(url_for("detalhes_pet", pet_id=pet_id))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

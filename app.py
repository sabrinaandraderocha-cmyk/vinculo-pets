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

# Chave secreta (em produção, use variável de ambiente FIXA no Render)
app.secret_key = os.getenv("SECRET_KEY", "chave-secreta-desenvolvimento-vinculo")

# =========================================================
# BANCO DE DADOS
# - Local: instance/database.db
# - Render (recomendado): setar DB_PATH=/var/data/database.db (Persistent Disk)
# =========================================================
DEFAULT_LOCAL_DB = os.path.join("instance", "database.db")
DB_PATH = os.getenv("DB_PATH", DEFAULT_LOCAL_DB)

# Garante pasta local instance (só faz sentido em dev/local)
os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "instance", exist_ok=True)


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
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass

def init_db():
    conn = get_db_connection()

    # Tabela de Usuários
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

    # Tabela de Pets
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

    # Migrações (Garante que colunas novas existam em bancos antigos)
    cols = [
        ("user_id INTEGER", "user_id"), ("tutor TEXT", "tutor"),
        ("resp1_tipo TEXT", "resp1_tipo"), ("resp1_nome TEXT", "resp1_nome"),
        ("resp2_tipo TEXT", "resp2_tipo"), ("resp2_nome TEXT", "resp2_nome"),
        ("musica_preferida TEXT", "musica_preferida"),
        ("vet_preferido TEXT", "vet_preferido"),
        ("motivo_nome TEXT", "motivo_nome"),
        ("alimentos_preferidos TEXT", "alimentos_preferidos"),
        ("alimentos_proibidos TEXT", "alimentos_proibidos"),
        ("quase_chamou TEXT", "quase_chamou"),
        ("como_conhecemos TEXT", "como_conhecemos"),
        ("atividade_preferida TEXT", "atividade_preferida")
    ]
    for col_def, col_name in cols:
        add_column_if_missing(conn, "pets", col_def, col_name)

    # Tabela de Registros (Diário)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER, data TEXT, nota TEXT, humor TEXT,
            categoria TEXT, personalidade_hoje TEXT,
            latindo INTEGER DEFAULT 0, mordeu_carteiro INTEGER DEFAULT 0,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "registros", "categoria TEXT", "categoria")
    add_column_if_missing(conn, "registros", "personalidade_hoje TEXT", "personalidade_hoje")
    add_column_if_missing(conn, "registros", "latindo INTEGER DEFAULT 0", "latindo")
    add_column_if_missing(conn, "registros", "mordeu_carteiro INTEGER DEFAULT 0", "mordeu_carteiro")

    # Tabela de Agenda
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER, tarefa TEXT, data_prevista TEXT,
            concluida INTEGER DEFAULT 0, created_at TEXT,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "agenda", "created_at TEXT", "created_at")

    # Tabela de Eventos
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER, tipo TEXT, data_evento TEXT,
            detalhes TEXT, criado_em TEXT,
            FOREIGN KEY (pet_id) REFERENCES pets (id)
        )
    """)
    add_column_if_missing(conn, "eventos", "criado_em TEXT", "criado_em")

    conn.commit()
    conn.close()


# Inicializa o banco ao rodar
init_db()


# =========================
# Auth & Helpers
# =========================
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

def current_user_id():
    return session.get("user_id")

def _placeholders(n: int) -> str:
    return ",".join(["?"] * n)

def fetch_pet_or_404(conn, pet_id):
    user_id = current_user_id()

    user = conn.execute("SELECT family_id FROM users WHERE id = ?", (user_id,)).fetchone()

    # Sem família => só o dono
    if not user or not user["family_id"]:
        pet = conn.execute(
            "SELECT * FROM pets WHERE id = ? AND user_id = ?",
            (pet_id, user_id)
        ).fetchone()
        if not pet:
            abort(404)
        return pet

    # Com família => qualquer membro da família
    members = conn.execute(
        "SELECT id FROM users WHERE family_id = ?",
        (user["family_id"],)
    ).fetchall()

    ids = [m["id"] for m in members]
    if not ids:
        abort(404)

    ph = _placeholders(len(ids))
    query = f"SELECT * FROM pets WHERE id = ? AND user_id IN ({ph})"
    params = [pet_id] + ids

    pet = conn.execute(query, params).fetchone()
    if not pet:
        abort(404)
    return pet

def get_responsaveis(pet_row):
    parts = []
    t1 = (pet_row["resp1_tipo"] or "").strip()
    n1 = (pet_row["resp1_nome"] or "").strip()
    t2 = (pet_row["resp2_tipo"] or "").strip()
    n2 = (pet_row["resp2_nome"] or "").strip()

    if t1 and n1:
        parts.append(f"{t1}: {n1}")
    if t2 and n2:
        parts.append(f"{t2}: {n2}")
    if not parts and (pet_row["tutor"] or "").strip():
        parts.append(f"Tutor: {pet_row['tutor'].strip()}")
    return parts


# Utils
CURIOSIDADES = {
    "gato": ["Gatos bebem pouca água; fontes ajudam.", "Ronronar nem sempre é alegria.", "Arranhar é instinto."],
    "cão": ["Passeios cheios de cheiros cansam mais.", "Mudança de apetite? Anote.", "Roer acalma a ansiedade."],
    "outro": ["Animais exóticos escondem dor.", "Rotina fixa reduz estresse.", "Enriquecimento ambiental é vital."]
}

def pick_curiosidade(especie):
    e = (especie or "").lower()
    if "gat" in e:
        pool = CURIOSIDADES["gato"]
    elif any(x in e for x in ["cã", "cao", "dog"]):
        pool = CURIOSIDADES["cão"]
    else:
        pool = CURIOSIDADES["outro"]
    return random.choice(pool)

def compute_wellbeing_summary(registros):
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    counts = {}
    total = 0

    for r in registros:
        try:
            dt = datetime.strptime(r["data"], "%d/%m/%Y %H:%M")
            if dt >= cutoff:
                total += 1
                h = (r["humor"] or "Neutro").strip()
                counts[h] = counts.get(h, 0) + 1
        except:
            continue

    top_humor, top_count = None, 0
    for k, v in counts.items():
        if v > top_count:
            top_humor, top_count = k, v

    return {"total_7d": total, "top_humor": top_humor, "top_count": top_count}


# =========================
# ROTAS DE AUTENTICAÇÃO
# =========================
@app.route("/signup", methods=("GET", "POST"))
def signup():
    # Se já estiver logado, não faz sentido cadastrar
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        code = request.form.get("invite_code", "").strip().upper()

        if not email or "@" not in email:
            flash("Digite um e-mail válido.", "error")
            return redirect(url_for("signup"))

        if not password or len(password) < 6:
            flash("Crie uma senha com pelo menos 6 caracteres.", "error")
            return redirect(url_for("signup"))

        conn = get_db_connection()
        try:
            # Já existe?
            if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                flash("E-mail já cadastrado. Tente fazer login.", "warning")
                return redirect(url_for("login"))

            # Família por código (opcional)
            if code:
                fam = conn.execute("SELECT family_id FROM users WHERE family_id = ?", (code,)).fetchone()
                if fam:
                    family_id = code
                    flash(f"Oba! Você entrou na família {code}!", "success")
                else:
                    family_id = gerar_codigo_familia()
                    flash("Código não encontrado. Criamos uma nova família para você.", "info")
            else:
                family_id = gerar_codigo_familia()

            pw_hash = generate_password_hash(password)
            created_at = datetime.now().strftime("%d/%m/%Y %H:%M")

            conn.execute(
                "INSERT INTO users (email, password_hash, created_at, family_id) VALUES (?, ?, ?, ?)",
                (email, pw_hash, created_at, family_id)
            )
            conn.commit()

            # ✅ NÃO loga automaticamente
            flash("Conta criada com sucesso! Faça login para continuar 🐾", "success")
            return redirect(url_for("login"))

        finally:
            conn.close()

    return render_template("signup.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    # Se já estiver logado, vai direto pro app
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Preencha e-mail e senha.", "error")
            return redirect(url_for("login"))

        conn = get_db_connection()
        try:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if not user or not check_password_hash(user["password_hash"], password):
                flash("E-mail ou senha incorretos.", "error")
                return redirect(url_for("login"))

            # Autocura (usuários antigos sem família)
            if not user["family_id"]:
                new_code = gerar_codigo_familia()
                conn.execute("UPDATE users SET family_id = ? WHERE id = ?", (new_code, user["id"]))
                conn.commit()

            # ✅ Login de verdade
            session.clear()
            session["user_id"] = user["id"]

            flash("Bem-vinda de volta! 🐶🐾", "success")
            return redirect(url_for("index"))

        finally:
            conn.close()

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Saiu com segurança.", "info")
    return redirect(url_for("login"))


# =========================
# ROTAS DO APP
# =========================
@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    user_id = current_user_id()

    user = conn.execute("SELECT family_id FROM users WHERE id = ?", (user_id,)).fetchone()

    pets = []
    my_code = "ERRO"

    if user:
        my_code = user["family_id"]
        if my_code:
            members = conn.execute("SELECT id FROM users WHERE family_id = ?", (my_code,)).fetchall()
            ids = [m["id"] for m in members]

            if ids:
                ph = _placeholders(len(ids))
                query = f"SELECT * FROM pets WHERE user_id IN ({ph}) ORDER BY id DESC"
                pets = conn.execute(query, ids).fetchall()
            else:
                pets = []
        else:
            pets = conn.execute("SELECT * FROM pets WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()

    conn.close()

    especie = pets[0]["especie"] if pets else "outro"
    return render_template(
        "index.html",
        pets=pets,
        curiosidade_home=pick_curiosidade(especie),
        my_code=my_code
    )


@app.route("/curiosidades")
@login_required
def curiosidades():
    return render_template("curiosidades.html", curiosidades=CURIOSIDADES)


@app.route("/cadastrar", methods=("GET", "POST"))
@login_required
def cadastrar():
    if request.method == "POST":
        f = request.form
        if not f.get("nome"):
            flash("O nome é obrigatório!", "error")
            return render_template("cadastro.html")

        conn = get_db_connection()

        conn.execute("""
            INSERT INTO pets (
                user_id, nome, especie, nascimento, obs, tutor,
                resp1_tipo, resp1_nome, resp2_tipo, resp2_nome,
                musica_preferida, vet_preferido, motivo_nome,
                alimentos_preferidos, alimentos_proibidos,
                quase_chamou, como_conhecemos, atividade_preferida
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            current_user_id(),
            f.get("nome"),
            f.get("especie"),
            f.get("nascimento"),
            f.get("obs"),

            # legado (você estava jogando resp1_nome no tutor)
            f.get("resp1_nome"),

            f.get("resp1_tipo"),
            f.get("resp1_nome"),
            f.get("resp2_tipo"),
            f.get("resp2_nome"),
            f.get("musica_preferida"),
            f.get("vet_preferido"),
            f.get("motivo_nome"),
            f.get("alimentos_preferidos"),
            f.get("alimentos_proibidos"),
            f.get("quase_chamou"),
            f.get("como_conhecemos"),
            f.get("atividade_preferida")
        ))

        conn.commit()
        conn.close()

        flash("Pet cadastrado com sucesso!", "success")
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
            UPDATE pets SET
            nome=?, especie=?, nascimento=?, obs=?,
            resp1_tipo=?, resp1_nome=?, resp2_tipo=?, resp2_nome=?,
            musica_preferida=?, vet_preferido=?, motivo_nome=?,
            alimentos_preferidos=?, alimentos_proibidos=?,
            quase_chamou=?, como_conhecemos=?, atividade_preferida=?
            WHERE id=?
        """, (
            f.get("nome"), f.get("especie"), f.get("nascimento"), f.get("obs"),
            f.get("resp1_tipo"), f.get("resp1_nome"),
            f.get("resp2_tipo"), f.get("resp2_nome"),
            f.get("musica_preferida"), f.get("vet_preferido"), f.get("motivo_nome"),
            f.get("alimentos_preferidos"), f.get("alimentos_proibidos"),
            f.get("quase_chamou"), f.get("como_conhecemos"), f.get("atividade_preferida"),
            pet_id
        ))
        conn.commit()
        conn.close()

        flash("Dados atualizados!", "success")
        return redirect(url_for("detalhes_pet", pet_id=pet_id))

    conn.close()
    return render_template("cadastro.html", pet=pet, edit_mode=True)


@app.route("/pet/<int:pet_id>")
@login_required
def detalhes_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    registros = conn.execute(
        "SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,)
    ).fetchall()

    agenda = conn.execute(
        "SELECT * FROM agenda WHERE pet_id = ? AND concluida = 0 ORDER BY data_prevista ASC",
        (pet_id,)
    ).fetchall()

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "detalhes.html",
        pet=pet,
        registros=registros,
        agenda_pend=agenda,
        eventos=eventos,
        summary=compute_wellbeing_summary(registros),
        curiosidade=pick_curiosidade(pet["especie"]),
        responsaveis=get_responsaveis(pet)
    )


# ✅ ROTA DE DIÁRIO CORRIGIDA (mantida)
@app.route("/pet/<int:pet_id>/anotar", methods=("POST",))
@login_required
def anotar(pet_id):
    f = request.form
    conn = get_db_connection()

    # garante permissão
    fetch_pet_or_404(conn, pet_id)

    if f.get("nota"):
        conn.execute("""
            INSERT INTO registros (
                pet_id, data, nota, humor, categoria, personalidade_hoje, latindo, mordeu_carteiro
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pet_id,
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            f.get("nota"),
            f.get("humor"),
            f.get("categoria"),
            f.get("personalidade_hoje"),
            1 if f.get("latindo") else 0,
            1 if f.get("mordeu_carteiro") else 0
        ))
        conn.commit()
        flash("Diário atualizado!", "success")

    conn.close()
    return redirect(url_for("detalhes_pet", pet_id=pet_id))


@app.route("/pet/<int:pet_id>/eventos")
@login_required
def eventos_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)
    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,)
    ).fetchall()
    conn.close()
    return render_template("eventos.html", pet=pet, eventos=eventos)


@app.route("/pet/<int:pet_id>/modo-vet")
@login_required
def modo_vet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    registros = conn.execute(
        "SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC LIMIT 20",
        (pet_id,)
    ).fetchall()

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC LIMIT 15",
        (pet_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "modo_vet.html",
        pet=pet,
        registros=registros,
        eventos=eventos,
        summary=compute_wellbeing_summary(registros),
        frase_extra=random.choice(["Tudo em ordem?", "Histórico ajuda muito."]),
        responsaveis=get_responsaveis(pet)
    )


# Rotas auxiliares (mantidas)
@app.route("/agenda/<int:agenda_id>/done", methods=("POST",))
@login_required
def agenda_done(agenda_id):
    conn = get_db_connection()
    conn.execute("UPDATE agenda SET concluida = 1 WHERE id = ?", (agenda_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # debug=True em produção não é recomendado, mas mantive igual ao seu.
    app.run(host="0.0.0.0", port=port, debug=True)

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

    # =========================
    # USERS (login)
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # =========================
    # PETS (perfil do pet)
    # - dados isolados por user_id
    # - inclui 2 responsáveis (Tutor/Papai/Mamãe)
    # - inclui música preferida
    # =========================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,

            nome TEXT,
            especie TEXT,
            nascimento TEXT,
            obs TEXT,

            tutor TEXT, -- legado (mantido)

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

    # Migrações leves (para bancos já existentes)
    add_column_if_missing(conn, "pets", "user_id INTEGER", "user_id")
    add_column_if_missing(conn, "pets", "tutor TEXT", "tutor")
    add_column_if_missing(conn, "pets", "resp1_tipo TEXT", "resp1_tipo")
    add_column_if_missing(conn, "pets", "resp1_nome TEXT", "resp1_nome")
    add_column_if_missing(conn, "pets", "resp2_tipo TEXT", "resp2_tipo")
    add_column_if_missing(conn, "pets", "resp2_nome TEXT", "resp2_nome")
    add_column_if_missing(conn, "pets", "musica_preferida TEXT", "musica_preferida")
    add_column_if_missing(conn, "pets", "vet_preferido TEXT", "vet_preferido")
    add_column_if_missing(conn, "pets", "motivo_nome TEXT", "motivo_nome")
    add_column_if_missing(conn, "pets", "alimentos_preferidos TEXT", "alimentos_preferidos")
    add_column_if_missing(conn, "pets", "alimentos_proibidos TEXT", "alimentos_proibidos")

    # =========================
    # REGISTROS (diário)
    # =========================
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

    # =========================
    # AGENDA (lembretes)
    # =========================
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

    # =========================
    # EVENTOS (vacina/cirurgia/hotelzinho etc.)
    # =========================
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
# Auth helpers
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
    t1 = (pet_row["resp1_tipo"] or "").strip()
    n1 = (pet_row["resp1_nome"] or "").strip()
    t2 = (pet_row["resp2_tipo"] or "").strip()
    n2 = (pet_row["resp2_nome"] or "").strip()

    if t1 and n1:
        parts.append(f"{t1}: {n1}")
    if t2 and n2:
        parts.append(f"{t2}: {n2}")

    # fallback campo legado
    if not parts and (pet_row["tutor"] or "").strip():
        parts.append(f"Tutor: {pet_row['tutor'].strip()}")

    return parts

# =========================
# Curiosidades (sem "treino")
# =========================
CURIOSIDADES = {
    "gato": [
        "Gatos costumam beber pouca água. Fontes/cascatas ajudam muitos a se hidratar melhor.",
        "Ronronar pode ser conforto, mas também pode aparecer em dor/estresse: observe o contexto.",
        "Arranhar é comunicação: marcação, alongamento e autocuidado (não é pirraça)."
    ],
    "cão": [
        "Passeios curtos, cheiros novos e rotina cuidam mais do que longas exceções.",
        "Mudanças de apetite, energia e sono valem registro — padrões ajudam o vet.",
        "Cheirar o mundo cansa: um passeio com estímulo olfativo pode relaxar mais do que andar rápido."
    ],
    "outro": [
        "Animais pequenos e aves tendem a esconder sintomas: mudanças sutis podem ser importantes.",
        "Rotina previsível e ambiente rico (brinquedos/esconderijos) reduzem estresse.",
        "Enriquecimento ambiental é cuidado: menos tédio, mais bem-estar."
    ]
}

def pick_curiosidade(especie):
    e = (especie or "").lower()
    if "gat" in e:
        pool = CURIOSIDADES["gato"]
    elif "cã" in e or "cao" in e or "dog" in e:
        pool = CURIOSIDADES["cão"]
    else:
        pool = CURIOSIDADES["outro"]
    return random.choice(pool)

def parse_dt_br(dt_str):
    try:
        return datetime.strptime(dt_str, "%d/%m/%Y %H:%M")
    except Exception:
        return None

def compute_wellbeing_summary(registros):
    now = datetime.now()
    cutoff = now - timedelta(days=7)

    counts = {}
    total = 0

    for r in registros:
        dt = parse_dt_br(r["data"])
        if not dt:
            continue
        if dt >= cutoff:
            total += 1
            humor = (r["humor"] or "Sem rótulo").strip()
            counts[humor] = counts.get(humor, 0) + 1

    top_humor, top_count = None, 0
    for k, v in counts.items():
        if v > top_count:
            top_humor, top_count = k, v

    return {"total_7d": total, "top_humor": top_humor, "top_count": top_count}

# =========================
# AUTH ROUTES
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
            return render_template("signup.html", error="Esse e-mail já existe. Faça login :)")

        pw_hash = generate_password_hash(password)
        created_at = datetime.now().strftime("%d/%m/%Y %H:%M")
        conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, pw_hash, created_at),
        )
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
            return render_template("login.html", error="E-mail ou senha inválidos.")

        session["user_id"] = user["id"]
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =========================
# HOME
# =========================
@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    pets = conn.execute(
        "SELECT * FROM pets WHERE user_id = ? ORDER BY id DESC",
        (current_user_id(),),
    ).fetchall()
    conn.close()

    especie = pets[0]["especie"] if pets else "outro"
    curiosidade_home = pick_curiosidade(especie)
    return render_template("index.html", pets=pets, curiosidade_home=curiosidade_home)

@app.route("/curiosidades")
@login_required
def curiosidades():
    return render_template("curiosidades.html", curiosidades=CURIOSIDADES)

# =========================
# CADASTRO PET
# =========================
@app.route("/cadastrar", methods=("GET", "POST"))
@login_required
def cadastrar():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        especie = request.form.get("especie", "").strip()
        nascimento = request.form.get("nascimento", "").strip()
        obs = request.form.get("obs", "").strip()

        resp1_tipo = request.form.get("resp1_tipo", "Tutor").strip()
        resp1_nome = request.form.get("resp1_nome", "").strip()
        resp2_tipo = request.form.get("resp2_tipo", "Tutor").strip()
        resp2_nome = request.form.get("resp2_nome", "").strip()

        musica_preferida = request.form.get("musica_preferida", "").strip()

        vet_preferido = request.form.get("vet_preferido", "").strip()
        motivo_nome = request.form.get("motivo_nome", "").strip()

        alimentos_preferidos = request.form.get("alimentos_preferidos", "").strip()
        alimentos_proibidos = request.form.get("alimentos_proibidos", "").strip()

        if not nome or not especie:
            return render_template("cadastro.html", error="Nome e espécie são obrigatórios.")

        tutor_legacy = resp1_nome or ""

        conn = get_db_connection()
        conn.execute(
            """INSERT INTO pets
               (user_id, nome, especie, nascimento, obs, tutor,
                resp1_tipo, resp1_nome, resp2_tipo, resp2_nome,
                musica_preferida,
                vet_preferido, motivo_nome,
                alimentos_preferidos, alimentos_proibidos)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                current_user_id(),
                nome, especie, nascimento, obs, tutor_legacy,
                resp1_tipo, resp1_nome, resp2_tipo, resp2_nome,
                musica_preferida,
                vet_preferido, motivo_nome,
                alimentos_preferidos, alimentos_proibidos
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    return render_template("cadastro.html")

# =========================
# DETALHES PET
# =========================
@app.route("/pet/<int:pet_id>")
@login_required
def detalhes_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    registros = conn.execute(
        "SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,),
    ).fetchall()

    agenda_pend = conn.execute(
        "SELECT * FROM agenda WHERE pet_id = ? AND concluida = 0 ORDER BY data_prevista ASC, id DESC",
        (pet_id,),
    ).fetchall()

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,),
    ).fetchall()

    summary = compute_wellbeing_summary(registros)
    curiosidade = pick_curiosidade(pet["especie"])
    responsaveis = get_responsaveis(pet)

    conn.close()

    return render_template(
        "detalhes.html",
        pet=pet,
        registros=registros,
        agenda_pend=agenda_pend,
        eventos=eventos,
        summary=summary,
        curiosidade=curiosidade,
        responsaveis=responsaveis
    )

# =========================
# ANOTAR (diário)
# =========================
@app.route("/pet/<int:pet_id>/anotar", methods=("POST",))
@login_required
def anotar(pet_id):
    nota = request.form.get("nota", "").strip()
    humor = request.form.get("humor", "").strip()
    categoria = request.form.get("categoria", "").strip()
    personalidade_hoje = request.form.get("personalidade_hoje", "").strip()
    latindo = 1 if request.form.get("latindo") == "on" else 0
    mordeu_carteiro = 1 if request.form.get("mordeu_carteiro") == "on" else 0

    if not nota:
        return redirect(url_for("detalhes_pet", pet_id=pet_id))

    data = datetime.now().strftime("%d/%m/%Y %H:%M")

    conn = get_db_connection()
    fetch_pet_or_404(conn, pet_id)

    conn.execute(
        """INSERT INTO registros
           (pet_id, data, nota, humor, categoria, personalidade_hoje, latindo, mordeu_carteiro)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (pet_id, data, nota, humor, categoria, personalidade_hoje, latindo, mordeu_carteiro),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("detalhes_pet", pet_id=pet_id))

# =========================
# EVENTOS
# =========================
@app.route("/pet/<int:pet_id>/eventos")
@login_required
def eventos_pet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,),
    ).fetchall()
    conn.close()

    return render_template("eventos.html", pet=pet, eventos=eventos)

@app.route("/pet/<int:pet_id>/eventos/add", methods=("POST",))
@login_required
def eventos_add(pet_id):
    tipo = request.form.get("tipo", "").strip()
    data_evento = request.form.get("data_evento", "").strip()
    detalhes = request.form.get("detalhes", "").strip()
    criado_em = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not tipo:
        return redirect(url_for("eventos_pet", pet_id=pet_id))

    conn = get_db_connection()
    fetch_pet_or_404(conn, pet_id)

    conn.execute(
        "INSERT INTO eventos (pet_id, tipo, data_evento, detalhes, criado_em) VALUES (?, ?, ?, ?, ?)",
        (pet_id, tipo, data_evento, detalhes, criado_em),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("eventos_pet", pet_id=pet_id))

@app.route("/eventos/<int:evento_id>/delete", methods=("POST",))
@login_required
def eventos_delete(evento_id):
    conn = get_db_connection()
    ev = conn.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if not ev:
        conn.close()
        abort(404)

    fetch_pet_or_404(conn, ev["pet_id"])

    conn.execute("DELETE FROM eventos WHERE id = ?", (evento_id,))
    conn.commit()
    pet_id = ev["pet_id"]
    conn.close()

    return redirect(url_for("eventos_pet", pet_id=pet_id))

# =========================
# AGENDA
# =========================
@app.route("/pet/<int:pet_id>/agenda/add", methods=("POST",))
@login_required
def agenda_add(pet_id):
    tarefa = request.form.get("tarefa", "").strip()
    data_prevista = request.form.get("data_prevista", "").strip()
    created_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not tarefa:
        return redirect(url_for("detalhes_pet", pet_id=pet_id))

    conn = get_db_connection()
    fetch_pet_or_404(conn, pet_id)

    conn.execute(
        "INSERT INTO agenda (pet_id, tarefa, data_prevista, concluida, created_at) VALUES (?, ?, ?, 0, ?)",
        (pet_id, tarefa, data_prevista, created_at),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("detalhes_pet", pet_id=pet_id))

@app.route("/agenda/<int:agenda_id>/done", methods=("POST",))
@login_required
def agenda_done(agenda_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM agenda WHERE id = ?", (agenda_id,)).fetchone()
    if not item:
        conn.close()
        abort(404)

    pet = fetch_pet_or_404(conn, item["pet_id"])

    conn.execute("UPDATE agenda SET concluida = 1 WHERE id = ?", (agenda_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("detalhes_pet", pet_id=pet["id"]))

@app.route("/agenda/<int:agenda_id>/delete", methods=("POST",))
@login_required
def agenda_delete(agenda_id):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM agenda WHERE id = ?", (agenda_id,)).fetchone()
    if not item:
        conn.close()
        abort(404)

    pet = fetch_pet_or_404(conn, item["pet_id"])

    conn.execute("DELETE FROM agenda WHERE id = ?", (agenda_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("detalhes_pet", pet_id=pet["id"]))

# =========================
# EXPORTAR TXT
# =========================
@app.route("/pet/<int:pet_id>/exportar")
@login_required
def exportar_txt(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    registros = conn.execute(
        "SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,),
    ).fetchall()

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC",
        (pet_id,),
    ).fetchall()

    conn.close()

    responsaveis = get_responsaveis(pet)
    resp_txt = ", ".join(responsaveis) if responsaveis else (pet["tutor"] or "-")

    conteudo = f"RELATÓRIO VÍNCULO — {pet['nome'].upper()}\n"
    conteudo += f"Responsáveis: {resp_txt}\n"
    conteudo += f"Espécie: {pet['especie']} | Nascimento: {pet['nascimento']}\n"
    conteudo += f"Sobre: {pet['obs'] or '-'}\n"
    conteudo += f"Vet preferido: {pet['vet_preferido'] or '-'}\n"
    conteudo += f"Motivo do nome: {pet['motivo_nome'] or '-'}\n"
    conteudo += f"Música preferida: {pet['musica_preferida'] or '-'}\n"
    conteudo += f"Alimentos preferidos: {pet['alimentos_preferidos'] or '-'}\n"
    conteudo += f"ALIMENTOS PROIBIDOS: {pet['alimentos_proibidos'] or '-'}\n"
    conteudo += "=" * 60 + "\n\n"

    conteudo += "EVENTOS (saúde e rotina)\n" + "-" * 40 + "\n"
    for e in eventos:
        conteudo += f"[{e['data_evento'] or '-'}] — {e['tipo']}\n"
        if e["detalhes"]:
            conteudo += f"Detalhes: {e['detalhes']}\n"
        conteudo += "-" * 20 + "\n"

    conteudo += "\nDIÁRIO (observações)\n" + "-" * 40 + "\n"
    for r in registros:
        cat = f" • Categoria: {r['categoria']}" if r["categoria"] else ""
        badges = []
        if r["personalidade_hoje"]:
            badges.append(r["personalidade_hoje"])
        if r["latindo"] == 1:
            badges.append("latindo")
        if r["mordeu_carteiro"] == 1:
            badges.append("mordeu o carteiro")
        extra = f" • Hoje: {', '.join(badges)}" if badges else ""

        conteudo += f"[{r['data']}] — Estado: {r['humor']}{cat}{extra}\n"
        conteudo += f"Relato: {r['nota']}\n"
        conteudo += "-" * 20 + "\n"

    conteudo += "\nGerado pelo App Vínculo — Sem fins de diagnóstico automático.\n"

    return Response(
        conteudo,
        mimetype="text/plain",
        headers={"Content-disposition": f"attachment; filename=vinculo_{pet['nome']}.txt"}
    )

# =========================
# MODO VET
# =========================
@app.route("/pet/<int:pet_id>/modo-vet")
@login_required
def modo_vet(pet_id):
    conn = get_db_connection()
    pet = fetch_pet_or_404(conn, pet_id)

    registros = conn.execute(
        "SELECT * FROM registros WHERE pet_id = ? ORDER BY id DESC LIMIT 20",
        (pet_id,),
    ).fetchall()

    eventos = conn.execute(
        "SELECT * FROM eventos WHERE pet_id = ? ORDER BY id DESC LIMIT 15",
        (pet_id,),
    ).fetchall()

    summary = compute_wellbeing_summary(registros)
    responsaveis = get_responsaveis(pet)
    conn.close()

    frases_vet = [
        "Vet preferido: escolhido por confiança, carinho e um leve medo do Google.",
        "Nome do pet: escolhido por motivos emocionais e/ou fofura incontestável.",
        "Paciente possivelmente ótimo… ou só atuando. Registro ajuda 😅",
    ]
    frase_extra = random.choice(frases_vet)

    return render_template(
        "modo_vet.html",
        pet=pet,
        registros=registros,
        eventos=eventos,
        summary=summary,
        frase_extra=frase_extra,
        responsaveis=responsaveis
    )

# =========================
# Run
# =========================
if __name__ == "__main__":
    init_db()
    # Para publicar online (Render etc.), use host/port
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)

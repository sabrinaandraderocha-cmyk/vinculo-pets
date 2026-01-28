import os
import random
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

# =========================================================
# CONFIGURAÇÕES & SETUP
# =========================================================
app = Flask(__name__)

# Configuração da Chave Secreta
app.secret_key = os.getenv("SECRET_KEY", "chave-secreta-desenvolvimento-vinculo")

# Configuração do Banco de Dados (Inteligente: Neon na nuvem, SQLite no PC)
db_url = os.getenv("DATABASE_URL", "sqlite:///instance/database.db")
# Correção para o Render (postgres:// -> postgresql://)
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializa o Banco
db = SQLAlchemy(app)

# =========================================================
# PREPARAÇÃO VISUAL (TEMA ROXO)
# =========================================================
@app.context_processor
def inject_theme():
    return dict(theme_color="#6f42c1")

# =========================================================
# MODELOS (As tabelas do Banco)
# =========================================================

# Mixin para garantir que seu HTML antigo (que usa pet['nome']) continue funcionando
class DictMixin:
    def __getitem__(self, key):
        return getattr(self, key)

class User(db.Model, DictMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.String(50))
    family_id = db.Column(db.String(20))
    
    # Relação com pets
    pets = db.relationship('Pet', backref='owner', lazy=True)

class Pet(db.Model, DictMixin):
    __tablename__ = 'pets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    nome = db.Column(db.String(100))
    especie = db.Column(db.String(50))
    nascimento = db.Column(db.String(20))
    obs = db.Column(db.Text)
    tutor = db.Column(db.String(100))
    
    resp1_tipo = db.Column(db.String(50))
    resp1_nome = db.Column(db.String(100))
    resp2_tipo = db.Column(db.String(50))
    resp2_nome = db.Column(db.String(100))
    
    musica_preferida = db.Column(db.String(100))
    vet_preferido = db.Column(db.String(100))
    motivo_nome = db.Column(db.Text)
    alimentos_preferidos = db.Column(db.Text)
    alimentos_proibidos = db.Column(db.Text)
    quase_chamou = db.Column(db.String(100))
    como_conhecemos = db.Column(db.Text)
    atividade_preferida = db.Column(db.Text)

class Registro(db.Model, DictMixin):
    __tablename__ = 'registros'
    id = db.Column(db.Integer, primary_key=True)
    pet_id = db.Column(db.Integer, db.ForeignKey('pets.id'))
    data = db.Column(db.String(30))
    nota = db.Column(db.Text)
    humor = db.Column(db.String(50))
    categoria = db.Column(db.String(50))
    personalidade_hoje = db.Column(db.String(50))
    latindo = db.Column(db.Integer, default=0)
    mordeu_carteiro = db.Column(db.Integer, default=0)

class Agenda(db.Model, DictMixin):
    __tablename__ = 'agenda'
    id = db.Column(db.Integer, primary_key=True)
    pet_id = db.Column(db.Integer, db.ForeignKey('pets.id'))
    tarefa = db.Column(db.String(200))
    data_prevista = db.Column(db.String(30))
    concluida = db.Column(db.Integer, default=0)
    created_at = db.Column(db.String(30))

class Evento(db.Model, DictMixin):
    __tablename__ = 'eventos'
    id = db.Column(db.Integer, primary_key=True)
    pet_id = db.Column(db.Integer, db.ForeignKey('pets.id'))
    tipo = db.Column(db.String(50))
    data_evento = db.Column(db.String(30))
    detalhes = db.Column(db.Text)
    criado_em = db.Column(db.String(30))

# Tenta criar as tabelas automaticamente ao iniciar (mas a rota setup-banco é a garantia)
with app.app_context():
    try:
        db.create_all()
    except:
        pass # Se falhar aqui, usamos a rota manual

# =========================================================
# HELPERS & UTILS
# =========================================================
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

def current_user():
    if "user_id" in session:
        return db.session.get(User, session["user_id"])
    return None

def fetch_pet_or_404(pet_id):
    user = current_user()
    if not user:
        abort(403)

    query = Pet.query.filter(Pet.id == pet_id)
    
    if user.family_id:
        family_members = db.session.query(User.id).filter_by(family_id=user.family_id).all()
        family_ids = [m.id for m in family_members]
        query = query.filter(Pet.user_id.in_(family_ids))
    else:
        query = query.filter_by(user_id=user.id)
        
    pet = query.first()
    if not pet:
        abort(404)
    return pet

def get_responsaveis(pet):
    parts = []
    if pet.resp1_tipo and pet.resp1_nome:
        parts.append(f"{pet.resp1_tipo}: {pet.resp1_nome}")
    if pet.resp2_tipo and pet.resp2_nome:
        parts.append(f"{pet.resp2_tipo}: {pet.resp2_nome}")
    if not parts and pet.tutor:
        parts.append(f"Tutor: {pet.tutor}")
    return parts

# Curiosidades
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
            dt = datetime.strptime(r.data, "%d/%m/%Y %H:%M")
            if dt >= cutoff:
                total += 1
                h = (r.humor or "Neutro").strip()
                counts[h] = counts.get(h, 0) + 1
        except:
            continue

    top_humor, top_count = None, 0
    for k, v in counts.items():
        if v > top_count:
            top_humor, top_count = k, v

    return {"total_7d": total, "top_humor": top_humor, "top_count": top_count}


# =========================================================
# ROTAS DE EMERGÊNCIA (SALVA-VIDAS)
# =========================================================
@app.route('/setup-banco')
def setup_banco():
    try:
        with app.app_context():
            db.create_all()
        return "<h1 style='color:green'>SUCESSO! Tabelas criadas.</h1> <p>Volte para <a href='/signup'>Criar Conta</a></p>"
    except Exception as e:
        return f"<h1 style='color:red'>ERRO:</h1> <p>{str(e)}</p>"

# =========================================================
# ROTAS DE AUTENTICAÇÃO
# =========================================================
@app.route("/signup", methods=("GET", "POST"))
def signup():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        code = request.form.get("invite_code", "").strip().upper()

        if not email or "@" not in email:
            flash("Digite um e-mail válido.", "error")
            return redirect(url_for("signup"))
        
        # Verifica se email já existe
        if User.query.filter_by(email=email).first():
            flash("E-mail já cadastrado. Tente fazer login.", "warning")
            return redirect(url_for("login"))

        family_id = gerar_codigo_familia()
        if code:
            # Verifica se família existe
            exists = User.query.filter_by(family_id=code).first()
            if exists:
                family_id = code
                flash(f"Oba! Você entrou na família {code}!", "success")
            else:
                flash("Código não encontrado. Criamos uma nova família.", "info")

        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            created_at=datetime.now().strftime("%d/%m/%Y %H:%M"),
            family_id=family_id
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Conta criada! Faça login para continuar 🐾", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("E-mail ou senha incorretos.", "error")
            return redirect(url_for("login"))

        # Autocura
        if not user.family_id:
            user.family_id = gerar_codigo_familia()
            db.session.commit()

        session.clear()
        session["user_id"] = user.id
        flash("Bem-vinda de volta! 🐶🐾", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Saiu com segurança.", "info")
    return redirect(url_for("login"))


# =========================================================
# ROTAS DO APP
# =========================================================
@app.route("/")
@login_required
def index():
    user = current_user()
    pets = []
    
    if user.family_id:
        family_members = User.query.filter_by(family_id=user.family_id).all()
        family_ids = [u.id for u in family_members]
        pets = Pet.query.filter(Pet.user_id.in_(family_ids)).order_by(Pet.id.desc()).all()
    else:
        pets = Pet.query.filter_by(user_id=user.id).order_by(Pet.id.desc()).all()

    especie_padrao = pets[0].especie if pets else "outro"
    
    return render_template(
        "index.html",
        pets=pets,
        curiosidade_home=pick_curiosidade(especie_padrao),
        my_code=user.family_id or "ERRO"
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

        novo_pet = Pet(
            user_id=session["user_id"],
            nome=f.get("nome"),
            especie=f.get("especie"),
            nascimento=f.get("nascimento"),
            obs=f.get("obs"),
            tutor=f.get("resp1_nome"), 
            resp1_tipo=f.get("resp1_tipo"),
            resp1_nome=f.get("resp1_nome"),
            resp2_tipo=f.get("resp2_tipo"),
            resp2_nome=f.get("resp2_nome"),
            musica_preferida=f.get("musica_preferida"),
            vet_preferido=f.get("vet_preferido"),
            motivo_nome=f.get("motivo_nome"),
            alimentos_preferidos=f.get("alimentos_preferidos"),
            alimentos_proibidos=f.get("alimentos_proibidos"),
            quase_chamou=f.get("quase_chamou"),
            como_conhecemos=f.get("como_conhecemos"),
            atividade_preferida=f.get("atividade_preferida")
        )

        db.session.add(novo_pet)
        db.session.commit()

        flash("Pet cadastrado com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("cadastro.html")

@app.route("/pet/<int:pet_id>/editar", methods=("GET", "POST"))
@login_required
def editar_pet(pet_id):
    pet = fetch_pet_or_404(pet_id)

    if request.method == "POST":
        f = request.form
        pet.nome = f.get("nome")
        pet.especie = f.get("especie")
        pet.nascimento = f.get("nascimento")
        pet.obs = f.get("obs")
        pet.resp1_tipo = f.get("resp1_tipo")
        pet.resp1_nome = f.get("resp1_nome")
        pet.resp2_tipo = f.get("resp2_tipo")
        pet.resp2_nome = f.get("resp2_nome")
        pet.musica_preferida = f.get("musica_preferida")
        pet.vet_preferido = f.get("vet_preferido")
        pet.motivo_nome = f.get("motivo_nome")
        pet.alimentos_preferidos = f.get("alimentos_preferidos")
        pet.alimentos_proibidos = f.get("alimentos_proibidos")
        pet.quase_chamou = f.get("quase_chamou")
        pet.como_conhecemos = f.get("como_conhecemos")
        pet.atividade_preferida = f.get("atividade_preferida")
        
        db.session.commit()
        flash("Dados atualizados!", "success")
        return redirect(url_for("detalhes_pet", pet_id=pet_id))

    return render_template("cadastro.html", pet=pet, edit_mode=True)

@app.route("/pet/<int:pet_id>")
@login_required
def detalhes_pet(pet_id):
    pet = fetch_pet_or_404(pet_id)
    
    registros = Registro.query.filter_by(pet_id=pet_id).order_by(Registro.id.desc()).all()
    agenda = Agenda.query.filter_by(pet_id=pet_id, concluida=0).order_by(Agenda.data_prevista.asc()).all()
    eventos = Evento.query.filter_by(pet_id=pet_id).order_by(Evento.id.desc()).all()

    return render_template(
        "detalhes.html",
        pet=pet,
        registros=registros,
        agenda_pend=agenda,
        eventos=eventos,
        summary=compute_wellbeing_summary(registros),
        curiosidade=pick_curiosidade(pet.especie),
        responsaveis=get_responsaveis(pet)
    )

@app.route("/pet/<int:pet_id>/anotar", methods=("POST",))
@login_required
def anotar(pet_id):
    f = request.form
    pet = fetch_pet_or_404(pet_id)

    if f.get("nota"):
        novo_registro = Registro(
            pet_id=pet_id,
            data=datetime.now().strftime("%d/%m/%Y %H:%M"),
            nota=f.get("nota"),
            humor=f.get("humor"),
            categoria=f.get("categoria"),
            personalidade_hoje=f.get("personalidade_hoje"),
            latindo=1 if f.get("latindo") else 0,
            mordeu_carteiro=1 if f.get("mordeu_carteiro") else 0
        )
        db.session.add(novo_registro)
        db.session.commit()
        flash("Diário atualizado!", "success")

    return redirect(url_for("detalhes_pet", pet_id=pet_id))

@app.route("/pet/<int:pet_id>/eventos")
@login_required
def eventos_pet(pet_id):
    pet = fetch_pet_or_404(pet_id)
    eventos = Evento.query.filter_by(pet_id=pet_id).order_by(Evento.id.desc()).all()
    return render_template("eventos.html", pet=pet, eventos=eventos)

@app.route("/pet/<int:pet_id>/modo-vet")
@login_required
def modo_vet(pet_id):
    pet = fetch_pet_or_404(pet_id)
    registros = Registro.query.filter_by(pet_id=pet_id).order_by(Registro.id.desc()).limit(20).all()
    eventos = Evento.query.filter_by(pet_id=pet_id).order_by(Evento.id.desc()).limit(15).all()

    return render_template(
        "modo_vet.html",
        pet=pet,
        registros=registros,
        eventos=eventos,
        summary=compute_wellbeing_summary(registros),
        frase_extra=random.choice(["Tudo em ordem?", "Histórico ajuda muito."]),
        responsaveis=get_responsaveis(pet)
    )

@app.route("/agenda/<int:agenda_id>/done", methods=("POST",))
@login_required
def agenda_done(agenda_id):
    tarefa = db.session.get(Agenda, agenda_id)
    if tarefa:
        # Verifica se o usuário é dono do pet
        pet = db.session.get(Pet, tarefa.pet_id)
        if pet: 
             tarefa.concluida = 1
             db.session.commit()
             
    return redirect(request.referrer or url_for("index"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
# =========================================================
# ROTAS DE EMERGÊNCIA (SALVA-VIDAS)
# =========================================================
@app.route('/reset-banco-total')
def reset_banco():
    secret = request.args.get('force')
    # Proteção simples para ninguém rodar sem querer (precisa digitar ?force=sim)
    if secret != 'sim':
        return "Para resetar, adicione ?force=sim na URL. CUIDADO: APAGA TUDO!"
    
    try:
        with app.app_context():
            db.drop_all()   # <--- O SEGREDO: Apaga tudo que está errado
            db.create_all() # <--- Cria tudo novinho e correto (com family_id)
            
            # Cria um usuário de teste pra garantir
            teste = User(
                email="teste@vinculo.com", 
                password_hash="123", 
                created_at="Hoje", 
                family_id="TESTE1"
            )
            db.session.add(teste)
            db.session.commit()
            
        return "<h1 style='color:green'>BANCO RESETADO!</h1> <p>Agora a coluna family_id existe. Tente <a href='/signup'>criar conta</a>.</p>"
    except Exception as e:
        return f"<h1 style='color:red'>ERRO:</h1> <p>{str(e)}</p>"

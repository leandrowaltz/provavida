import os
import csv
import io
import tempfile
import base64
import pytz
import locale
from datetime import datetime, date, timedelta
from flask import Flask, request, jsonify, render_template, Response, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import func, JSON, and_
from functools import wraps
from fpdf import FPDF

# --- Configuração da Aplicação ---
app = Flask(__name__, template_folder='frontend', static_folder='frontend')
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)

# --- Autenticação ---
ADMIN_USERNAME = 'administrador'
ADMIN_PASSWORD = 'admin!alprev!'

def check_auth(username, password):
    """Verifica se as credenciais estão corretas e retorna o objeto do utilizador."""
    user = User.query.filter_by(username=username).first()
    if user and user.password == password:
        return user
    return None

def requires_auth(f):
    """Decorator para proteger rotas com autenticação Basic."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response('Acesso não autorizado.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
        return f(*args, **kwargs)
    return decorated

def requires_admin_auth(f):
    """Decorator para proteger rotas que exigem privilégios de administrador."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (auth.username == ADMIN_USERNAME and auth.password == ADMIN_PASSWORD):
            return Response('Acesso restrito a administradores.', 403)
        return f(*args, **kwargs)
    return decorated

# --- Modelos do Banco de Dados ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    permissions = db.Column(JSON)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "permissions": self.permissions
        }

class Cadastro(db.Model):
    __tablename__ = 'cadastros'
    cpf = db.Column(db.String(14), primary_key=True)
    matricula = db.Column(db.String(100), nullable=True)
    nome = db.Column(db.String(255), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    is_whatsapp = db.Column(db.Boolean, nullable=False)
    qualidade = db.Column(db.String(100), nullable=False)
    data_atendimento = db.Column(db.Date, nullable=False)
    informacao = db.Column(db.Text, nullable=True)
    obs = db.Column(db.Text, nullable=True)
    atendente_criacao = db.Column(db.String(100), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    atendente_modificacao = db.Column(db.String(100), nullable=True)
    data_modificacao = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
    necessita_visita_social = db.Column(db.Boolean, default=False)
    status_visita = db.Column(db.String(50), nullable=True)
    processo = db.Column(db.String(100), nullable=True)
    endereco = db.Column(db.Text, nullable=True)
    assunto_visita = db.Column(db.Text, nullable=True)
    tem_procurador = db.Column(db.Boolean, default=False)
    procurador_nome = db.Column(db.String(255), nullable=True)
    procurador_cpf = db.Column(db.String(14), nullable=True)
    tem_curador = db.Column(db.Boolean, default=False)
    curador_nome = db.Column(db.String(255), nullable=True)
    curador_cpf = db.Column(db.String(14), nullable=True)
    nome_documento = db.Column(db.String(255), nullable=True)
    documento_pdf = db.Column(db.LargeBinary, nullable=True)
    foto_segurado = db.Column(db.LargeBinary, nullable=True)

    def to_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns if c.name not in ['documento_pdf', 'foto_segurado']}
        for key, value in data.items():
            if isinstance(value, (datetime, date)):
                data[key] = value.isoformat()
        data['has_document'] = True if self.documento_pdf else False
        data['has_photo'] = True if self.foto_segurado else False
        return data

class AuditoriaAlteracoes(db.Model):
    __tablename__ = 'auditoria_alteracoes'
    id = db.Column(db.Integer, primary_key=True)
    cadastro_cpf = db.Column(db.String(14), db.ForeignKey('cadastros.cpf'), nullable=False)
    atendente = db.Column(db.String(100), nullable=False)
    data_alteracao = db.Column(db.DateTime, default=datetime.utcnow)
    campo_alterado = db.Column(db.String(100), nullable=False)
    valor_antigo = db.Column(db.Text, nullable=True)
    valor_novo = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {c.name: getattr(self, c.name).isoformat() if isinstance(getattr(self, c.name), datetime) else getattr(self, c.name) for c in self.__table__.columns}

# --- Classes para Geração de PDF ---
class BasePDF(FPDF):
    def header(self):
        try:
            logo_path = os.path.join(app.static_folder, 'logo.png')
            if os.path.exists(logo_path):
                self.image(logo_path, 10, 8, 33)
        except Exception as e:
            app.logger.error(f"Erro ao carregar o logo no PDF: {e}")
        self.set_font('Arial', 'B', 10)
        self.set_xy(50, 15)
        self.cell(0, 5, 'ESTADO DE ALAGOAS', 0, 2, 'L')
        self.cell(0, 5, 'SECRETARIA DE ESTADO DO PLANEJAMENTO, GESTÃO E PATRIMÔNIO', 0, 2, 'L')
        self.cell(0, 5, 'ALAGOAS PREVIDÊNCIA', 0, 2, 'L')
        self.set_line_width(0.5)
        self.line(10, 45, self.w - 10, 45)
        self.ln(20)

    def footer(self):
        self.set_y(-25)
        self.set_font('Arial', 'I', 8)
        self.set_line_width(0.5)
        self.line(self.get_x(), self.get_y(), self.get_x() + self.w - 20, self.get_y())
        self.ln(2)
        self.cell(0, 5, 'Avenida da Paz, 1864, Empresarial Terra Brasilis - Térreo, 13º, 14º e 15º andares, Centro, Maceió-AL. CEP 57020-440', 0, 1, 'C')
        self.cell(0, 5, 'CNPJ 23.658.211/0001-11 - Telefones - Geral: (82) 3315-1831 / Call Center: (82) 3315-5707', 0, 1, 'C')

class StatisticsPDF(BasePDF):
    def chapter_title(self, title):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, title, 0, 1, 'C')
        self.ln(10)

    def add_kpi(self, title, value):
        self.set_font('Arial', '', 12)
        self.cell(90, 10, f'{title}:', 0, 0, 'R')
        self.set_font('Arial', 'B', 12)
        self.cell(20, 10, str(value), 0, 1, 'L')

    def add_data_table(self, title, data):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 15, title, 0, 1, 'L')
        self.set_font('Arial', '', 10)
        for key, value in data.items():
            self.cell(50, 8, str(key), 1, 0)
            self.cell(50, 8, str(value), 1, 1)
        self.ln(5)

class CadastroPDF(BasePDF):
    def __init__(self):
        super().__init__()
        self.photo_path = None

    def set_photo_path(self, path):
        self.photo_path = path

    def header(self):
        super().header()
        if self.photo_path:
            self.image(self.photo_path, 160, 40, 40, 40)
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Ficha de Cadastro', 0, 1, 'C')
        self.ln(5)

    def add_field(self, title, content):
        self.set_font('Arial', 'B', 10)
        self.cell(40, 7, str(title), 0, 0)
        self.set_font('Arial', '', 10)
        self.multi_cell(110, 7, str(content), 0, 'L')

    def add_section_title(self, title):
        self.ln(5)
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title, 'B', 1, 'L')
        self.ln(2)

class DeclaracaoPDF(BasePDF):
    def header(self):
        super().header()
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'DECLARAÇÃO DE COMPARECIMENTO - PROVA DE VIDA', 0, 1, 'C')
        self.ln(15)

    def body_text(self, cadastro):
        self.set_font('Arial', '', 12)

        representante_texto = ""
        if cadastro.tem_procurador and cadastro.procurador_nome:
            representante_texto = f"neste ato devidamente representado(a) por seu(sua) procurador(a), {cadastro.procurador_nome}, inscrito(a) no CPF sob o número {cadastro.procurador_cpf},"
        elif cadastro.tem_curador and cadastro.curador_nome:
            representante_texto = f"neste ato devidamente representado(a) por seu(sua) curador(a), {cadastro.curador_nome}, inscrito(a) no CPF sob o número {cadastro.curador_cpf},"

        if representante_texto:
            texto = f"Declaro que o Sr(a). {cadastro.nome}, inscrito no CPF sob o número {cadastro.cpf}, {representante_texto} solicitou suporte nesta Unidade Gestora na presente data para realizar a prova de vida."
        else:
            texto = f"Declaro que o Sr(a). {cadastro.nome}, inscrito no CPF sob o número {cadastro.cpf}, compareceu nesta Unidade Gestora na presente data, solicitando suporte para realizar a prova de vida digital pelo sistema E-GOV, a mesma apresentou a documentação pessoal, bem como realizou captura fotográfica."

        self.multi_cell(0, 8, texto.encode('latin-1', 'replace').decode('latin-1'))
        self.ln(20)

    def signature_section(self, cadastro):
        try:
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
            today_str = datetime.now(pytz.timezone('America/Maceio')).strftime("%d de %B de %Y.")
        except locale.Error:
            now = datetime.now(pytz.timezone('America/Maceio'))
            months_pt = {
                1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
                5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
            }
            today_str = f"{now.day} de {months_pt[now.month]} de {now.year}."

        self.set_font('Arial', '', 10)
        self.cell(0, 10, f"Maceió, {today_str}", 0, 1, 'C')
        self.ln(15)

        # Assinatura do Segurado ou Representante
        self.ln(15) # Espaço para a assinatura
        if cadastro.tem_procurador and cadastro.procurador_nome:
            self.cell(0, 5, cadastro.procurador_nome.encode('latin-1', 'replace').decode('latin-1'), 0, 1, 'C')
            self.cell(0, 5, f"CPF: {cadastro.procurador_cpf}", 0, 1, 'C')
            self.cell(0, 5, 'Procurador(a)', 0, 1, 'C')
        elif cadastro.tem_curador and cadastro.curador_nome:
            self.cell(0, 5, cadastro.curador_nome.encode('latin-1', 'replace').decode('latin-1'), 0, 1, 'C')
            self.cell(0, 5, f"CPF: {cadastro.curador_cpf}", 0, 1, 'C')
            self.cell(0, 5, 'Curador(a)', 0, 1, 'C')
        else:
            self.cell(0, 5, cadastro.nome.encode('latin-1', 'replace').decode('latin-1'), 0, 1, 'C')
            self.cell(0, 5, f"CPF: {cadastro.cpf}", 0, 1, 'C')
            self.cell(0, 5, cadastro.qualidade.encode('latin-1', 'replace').decode('latin-1'), 0, 1, 'C')
        self.ln(15)

        # Assinatura do Atendente
        self.ln(15) # Espaço para a assinatura
        self.cell(0, 5, cadastro.atendente_criacao.encode('latin-1', 'replace').decode('latin-1'), 0, 1, 'C')
        self.cell(0, 5, 'Atendente', 0, 1, 'C')

class RelatorioPDF(BasePDF):
    def header(self):
        super().header()
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Relatório de Visitas Sociais', 0, 1, 'C')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(4)

    def table(self, header, data):
        self.set_font('Arial', 'B', 9)
        col_widths = [30, 50, 80, 30] 
        line_height = 8
        for i, header_text in enumerate(header):
            self.cell(col_widths[i], line_height, header_text, 1, 0, 'C')
        self.ln(line_height)

        self.set_font('Arial', '', 8)
        for row in data:
            y_start = self.get_y()
            x_start = self.get_x()
            max_y = y_start

            for i, item in enumerate(row):
                self.set_xy(x_start + sum(col_widths[:i]), y_start)
                self.multi_cell(col_widths[i], 5, str(item), 0, 'L')
                if self.get_y() > max_y:
                    max_y = self.get_y()

            self.set_xy(x_start, y_start)
            for i in range(len(header)):
                self.cell(col_widths[i], max_y - y_start, '', 1, 0)
            self.ln(max_y - y_start)

# --- Rotas ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/cadastros', methods=['GET'])
@requires_auth
def get_all_cadastros():
    cpf_filter = request.args.get('cpf')
    query = Cadastro.query
    if cpf_filter:
        query = query.filter(Cadastro.cpf.like(f"%{cpf_filter}%"))
    todos_cadastros = query.order_by(Cadastro.nome).all()
    return jsonify([c.to_dict() for c in todos_cadastros])

@app.route('/api/cadastro', methods=['POST'])
@requires_auth
def criar_cadastro():
    data = request.form
    if Cadastro.query.get(data['cpf']):
        return jsonify({'error': 'CPF já cadastrado'}), 409

    foto_data = data.get('foto_segurado')
    decoded_image = None
    if foto_data:
        try:
            if ',' in foto_data:
                image_data = foto_data.split(',', 1)[1]
            else:
                image_data = foto_data

            image_data += '=' * (-len(image_data) % 4)
            decoded_image = base64.b64decode(image_data)
        except (IndexError, base64.binascii.Error) as e:
            app.logger.error(f"Erro ao decodificar imagem: {e}")
            return jsonify({'error': 'Formato de imagem inválido. Não foi possível processar a foto.'}), 400

    novo_cadastro = Cadastro(
        cpf=data['cpf'], nome=data['nome'], telefone=data['telefone'],
        email=data.get('email'),
        matricula=data.get('matricula'),
        is_whatsapp=data['is_whatsapp'].lower() == 'sim', qualidade=data['qualidade'],
        data_atendimento=datetime.strptime(data['data_atendimento'], '%Y-%m-%d').date(),
        informacao=data.get('informacao'), obs=data.get('obs'),
        atendente_criacao=data['atendente'],
        necessita_visita_social=data.get('necessita_visita_social') == 'on',
        tem_procurador=data.get('tem_procurador') == 'on',
        procurador_nome=data.get('procurador_nome'),
        procurador_cpf=data.get('procurador_cpf'),
        tem_curador=data.get('tem_curador') == 'on',
        curador_nome=data.get('curador_nome'),
        curador_cpf=data.get('curador_cpf'),
        foto_segurado=decoded_image
    )
    if novo_cadastro.necessita_visita_social:
        novo_cadastro.status_visita = 'Pendente'
        novo_cadastro.processo = data.get('processo')
        novo_cadastro.endereco = data.get('endereco')
        novo_cadastro.assunto_visita = data.get('assunto_visita')
    if 'documento' in request.files:
        file = request.files['documento']
        if file.filename != '':
            novo_cadastro.nome_documento = file.filename
            novo_cadastro.documento_pdf = file.read()
    db.session.add(novo_cadastro)
    db.session.commit()
    return jsonify(novo_cadastro.to_dict()), 201

@app.route('/api/cadastro/<cpf>/foto', methods=['POST'])
@requires_auth
def upload_foto(cpf):
    """Rota para upload/atualização de foto do segurado via base64."""
    cadastro = Cadastro.query.get_or_404(cpf)
    data = request.get_json()

    if not data or 'foto_base64' not in data:
        return jsonify({'error': 'Dados da foto (base64) não fornecidos'}), 400
    
    foto_data = data['foto_base64']
    
    try:
        if ',' in foto_data:
            image_data = foto_data.split(',', 1)[1]
        else:
            image_data = foto_data

        # Adiciona padding se necessário
        image_data += '=' * (-len(image_data) % 4)
        decoded_image = base64.b64decode(image_data)
        
        cadastro.foto_segurado = decoded_image
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Foto atualizada com sucesso!'}), 200

    except (IndexError, base64.binascii.Error) as e:
        app.logger.error(f"Erro ao decodificar imagem para CPF {cpf}: {e}")
        return jsonify({'error': 'Formato de imagem inválido.'}), 400


@app.route('/api/cadastro/<cpf>', methods=['PUT'])
@requires_auth
def editar_cadastro(cpf):
    cadastro = Cadastro.query.get_or_404(cpf)
    data = request.get_json()
    atendente = data.get('atendente')
    if not atendente: return jsonify({'error': 'Nome do atendente é obrigatório para editar'}), 400
    campos_para_comparar = ['nome', 'telefone', 'email', 'matricula', 'is_whatsapp', 'qualidade', 'data_atendimento', 'informacao', 'obs', 'processo', 'endereco', 'assunto_visita', 'procurador_nome', 'procurador_cpf', 'curador_nome', 'curador_cpf']
    for campo in campos_para_comparar:
        if campo in data:
            valor_novo_str = str(data.get(campo, ''))
            if campo == 'is_whatsapp':
                valor_novo_bool = valor_novo_str.lower() == 'sim'
                if valor_novo_bool != cadastro.is_whatsapp:
                    log = AuditoriaAlteracoes(cadastro_cpf=cpf, atendente=atendente, campo_alterado=campo, valor_antigo='Sim' if cadastro.is_whatsapp else 'Não', valor_novo='Sim' if valor_novo_bool else 'Não')
                    db.session.add(log)
                    cadastro.is_whatsapp = valor_novo_bool
            elif campo == 'data_atendimento':
                valor_novo_date = datetime.strptime(valor_novo_str, '%Y-%m-%d').date()
                if valor_novo_date != cadastro.data_atendimento:
                    log = AuditoriaAlteracoes(cadastro_cpf=cpf, atendente=atendente, campo_alterado=campo, valor_antigo=str(cadastro.data_atendimento), valor_novo=str(valor_novo_date))
                    db.session.add(log)
                    cadastro.data_atendimento = valor_novo_date
            else:
                valor_antigo_str = str(getattr(cadastro, campo) or '')
                if valor_novo_str != valor_antigo_str:
                    log = AuditoriaAlteracoes(cadastro_cpf=cpf, atendente=atendente, campo_alterado=campo, valor_antigo=valor_antigo_str, valor_novo=valor_novo_str)
                    db.session.add(log)
                    setattr(cadastro, campo, data.get(campo))
    cadastro.atendente_modificacao = atendente
    db.session.commit()
    return jsonify(cadastro.to_dict())

@app.route('/api/documento/<cpf>', methods=['GET'])
def get_documento(cpf):
    cadastro = Cadastro.query.get(cpf)
    if not cadastro or not cadastro.documento_pdf: return "Documento não encontrado", 404
    return send_file(io.BytesIO(cadastro.documento_pdf), mimetype='application/pdf', as_attachment=False, download_name=cadastro.nome_documento or 'documento.pdf')

@app.route('/api/foto/<cpf>', methods=['GET'])
def get_foto(cpf):
    cadastro = Cadastro.query.get(cpf)
    if not cadastro or not cadastro.foto_segurado: return "Foto não encontrada", 404
    return send_file(io.BytesIO(cadastro.foto_segurado), mimetype='image/jpeg')

@app.route('/api/visitas/<status>', methods=['GET'])
@requires_auth
def get_visitas(status):
    if status == 'pendentes':
        visitas = Cadastro.query.filter_by(status_visita='Pendente').order_by(Cadastro.nome).all()
    elif status == 'realizadas':
        visitas = Cadastro.query.filter_by(status_visita='Realizada').order_by(Cadastro.nome).all()
    else:
        return jsonify({'error': 'Status inválido'}), 400
    return jsonify([v.to_dict() for v in visitas])

@app.route('/api/visita/realizar/<cpf>', methods=['POST'])
@requires_auth
def marcar_visita_realizada(cpf):
    cadastro = Cadastro.query.get(cpf)
    if not cadastro: return jsonify({'error': 'Cadastro não encontrado'}), 404
    cadastro.status_visita = 'Realizada'
    db.session.commit()
    return jsonify({'success': True, 'message': 'Visita marcada como realizada.'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Utilizador e senha são obrigatórios'}), 400

    user = User.query.filter_by(username=data['username']).first()
    if user and user.password == data['password']:
        return jsonify({"success": True, "user": user.to_dict()})

    return jsonify({'success': False, 'error': 'Credenciais inválidas'}), 401

@app.route('/api/change-password', methods=['POST'])
@requires_auth
def change_password():
    """Rota para alteração de senha do usuário"""
    data = request.get_json()
    auth = request.authorization

    if not data or not data.get('new_password'):
        return jsonify({'error': 'Nova senha é obrigatória'}), 400

    # Verificar se é um usuário normal tentando alterar sua própria senha
    if auth.username != ADMIN_USERNAME:
        if not data.get('current_password'):
            return jsonify({'error': 'Senha atual é obrigatória'}), 400

        # Verificar senha atual
        user = User.query.filter_by(username=auth.username).first()
        if not user or user.password != data['current_password']:
            return jsonify({'error': 'Senha atual incorreta'}), 400

        # Alterar senha
        user.password = data['new_password']
        db.session.commit()
        return jsonify({'success': True, 'message': 'Senha alterada com sucesso!'})

    return jsonify({'error': 'Operação não permitida'}), 403

@app.route('/api/reset-password', methods=['POST'])
@requires_admin_auth
def reset_password():
    """Rota para reset de senha por administrador"""
    data = request.get_json()

    if not data or not data.get('user_id') or not data.get('new_password'):
        return jsonify({'error': 'ID do usuário e nova senha são obrigatórios'}), 400

    user = User.query.get(data['user_id'])
    if not user:
        return jsonify({'error': 'Usuário não encontrado'}), 404

    # Administrador não pode resetar sua própria senha por esta rota
    if user.username == ADMIN_USERNAME:
        return jsonify({'error': 'Não é possível resetar a senha do administrador'}), 403

    user.password = data['new_password']
    db.session.commit()

    return jsonify({'success': True, 'message': 'Senha resetada com sucesso!'})

@app.route('/api/users', methods=['GET'])
@requires_admin_auth
def get_users():
    users = User.query.all()
    return jsonify([user.to_dict() for user in users])

@app.route('/api/users', methods=['POST'])
@requires_admin_auth
def create_user():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Utilizador e senha são obrigatórios'}), 400

    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Utilizador já existe'}), 409

    new_user = User(
        username=data['username'],
        password=data['password'],
        permissions=data.get('permissions', {})
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify(new_user.to_dict()), 201

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@requires_admin_auth
def update_user_permissions(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    if 'permissions' in data:
        user.permissions = data['permissions']
        db.session.commit()
        return jsonify(user.to_dict())
    return jsonify({'error': 'Nenhuma permissão fornecida'}), 400

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@requires_admin_auth
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Utilizador não encontrado'}), 404
    if user.username == 'administrador':
        return jsonify({'error': 'Não é possível apagar o utilizador administrador'}), 403

    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Utilizador apagado com sucesso.'})

@app.route('/api/audit_logs', methods=['GET'])
@requires_auth
def get_audit_logs():
    cpf_filter = request.args.get('cpf')
    query = AuditoriaAlteracoes.query
    if cpf_filter:
        query = query.filter(AuditoriaAlteracoes.cadastro_cpf.like(f"%{cpf_filter}%"))
    logs = query.order_by(AuditoriaAlteracoes.data_alteracao.desc()).all()
    return jsonify([log.to_dict() for log in logs])

def _get_statistics_data():
    """Helper function to fetch statistics data."""
    total_cadastros = db.session.query(func.count(Cadastro.cpf)).scalar() or 0
    visitas_pendentes = Cadastro.query.filter_by(status_visita='Pendente').count()
    visitas_realizadas = Cadastro.query.filter_by(status_visita='Realizada').count()
    
    qualidade_counts = db.session.query(Cadastro.qualidade, func.count(Cadastro.qualidade)).group_by(Cadastro.qualidade).all()
    qualidade_data = {q: c for q, c in qualidade_counts}
    
    today = date.today()
    last_7_days = [today - timedelta(days=i) for i in range(7)]
    daily_counts_query = db.session.query(func.cast(Cadastro.data_atendimento, db.Date), func.count(Cadastro.data_atendimento)).filter(func.cast(Cadastro.data_atendimento, db.Date).in_(last_7_days)).group_by(func.cast(Cadastro.data_atendimento, db.Date)).all()
    daily_data_from_db = {d.strftime('%Y-%m-%d'): c for d, c in daily_counts_query}
    daily_data = {day.strftime('%d/%m'): daily_data_from_db.get(day.strftime('%Y-%m-%d'), 0) for day in reversed(last_7_days)}

    com_whatsapp = Cadastro.query.filter_by(is_whatsapp=True).count()
    whatsapp_data = {
        "Com WhatsApp": com_whatsapp,
        "Sem WhatsApp": total_cadastros - com_whatsapp
    }
    
    com_email = Cadastro.query.filter(and_(Cadastro.email.isnot(None), Cadastro.email != '')).count()
    email_data = {
        "Com Email": com_email,
        "Sem Email": total_cadastros - com_email
    }
    
    return {
        'total_cadastros': total_cadastros,
        'visitas_pendentes': visitas_pendentes,
        'visitas_realizadas': visitas_realizadas,
        'qualidade_data': qualidade_data,
        'daily_data': daily_data,
        'whatsapp_data': whatsapp_data,
        'email_data': email_data
    }

@app.route('/api/statistics', methods=['GET'])
@requires_auth
def get_statistics():
    try:
        stats_data = _get_statistics_data()
        return jsonify(stats_data)
    except Exception as e:
        app.logger.error(f"Erro ao buscar estatísticas: {e}")
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/export/statistics/pdf', methods=['GET'])
@requires_auth
def export_statistics_pdf():
    try:
        stats_data = _get_statistics_data()
        
        pdf = StatisticsPDF()
        pdf.add_page()
        pdf.chapter_title('Relatório de Estatísticas')
        
        pdf.add_kpi('Total de Cadastros', stats_data['total_cadastros'])
        pdf.add_kpi('Visitas Sociais Pendentes', stats_data['visitas_pendentes'])
        pdf.add_kpi('Visitas Sociais Realizadas', stats_data['visitas_realizadas'])
        pdf.ln(10)

        pdf.add_data_table('Distribuição por Qualidade', stats_data['qualidade_data'])
        pdf.add_data_table('Uso de WhatsApp', stats_data['whatsapp_data'])
        pdf.add_data_table('Uso de Email', stats_data['email_data'])
        
        return Response(pdf.output(dest='S').encode('latin-1'),
                        mimetype='application/pdf',
                        headers={'Content-Disposition': 'attachment;filename=relatorio_estatisticas.pdf'})
                        
    except Exception as e:
        app.logger.error(f"Erro ao gerar PDF de estatísticas: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/all', methods=['GET'])
@requires_auth
def exportar_tudo_csv():
    cadastros = Cadastro.query.all()
    if not cadastros: return "Nenhum cadastro para exportar", 404
    output = io.StringIO()
    writer = csv.writer(output)
    keys = [c.name for c in Cadastro.__table__.columns if c.name not in ['documento_pdf', 'nome_documento', 'foto_segurado']]
    writer.writerow(keys)
    for cadastro in cadastros:
        writer.writerow([getattr(cadastro, k) for k in keys])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=export_total_{datetime.now().strftime('%Y%m%d')}.csv"})

@app.route('/api/export/whatsapp', methods=['GET'])
@requires_auth
def exportar_whatsapp_csv():
    cadastros_whatsapp = Cadastro.query.filter_by(is_whatsapp=True).all()
    if not cadastros_whatsapp: return "Nenhum cadastro com WhatsApp para exportar", 404
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Nome', 'Telefone'])
    for cadastro in cadastros_whatsapp: writer.writerow([cadastro.nome, cadastro.telefone])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=contatos_whatsapp_{datetime.now().strftime('%Y%m%d')}.csv"})

@app.route('/api/export/visitas/<status>/<format>', methods=['GET'])
@requires_auth
def exportar_visitas(status, format):
    if status == 'pendentes':
        visitas = Cadastro.query.filter_by(status_visita='Pendente').order_by(Cadastro.nome).all()
    elif status == 'realizadas':
        visitas = Cadastro.query.filter_by(status_visita='Realizada').order_by(Cadastro.nome).all()
    else:
        return "Status inválido", 400

    if not visitas:
        return f"Nenhuma visita {status} para exportar", 404

    if format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        header = ['CPF', 'Nome', 'Telefone', 'Endereço', 'Assunto', 'Processo']
        writer.writerow(header)
        for visita in visitas:
            writer.writerow([visita.cpf, visita.nome, visita.telefone, visita.endereco, visita.assunto_visita, visita.processo])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=visitas_{status}.csv"})

    elif format == 'pdf':
        pdf = RelatorioPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.chapter_title(f'Relatório de Visitas {status.capitalize()}')
        header = ['CPF', 'Nome', 'Endereço', 'Assunto']
        data = [[v.cpf, v.nome, v.endereco or 'N/A', v.assunto_visita or 'N/A'] for v in visitas]
        pdf.table(header, data)
        return Response(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf', headers={'Content-Disposition': f'attachment;filename=visitas_{status}.pdf'})

    return "Formato inválido", 400

@app.route('/api/export/declaracao/<cpf>', methods=['GET'])
@requires_auth
def exportar_declaracao_pdf(cpf):
    cadastro = Cadastro.query.get(cpf)
    if not cadastro:
        return "Cadastro não encontrado", 404

    pdf = DeclaracaoPDF()
    pdf.add_page()
    pdf.body_text(cadastro)
    pdf.signature_section(cadastro)

    return Response(pdf.output(dest='S').encode('latin-1'), mimetype='application/pdf', headers={'Content-Disposition': f'attachment;filename=declaracao_{cadastro.cpf}.pdf'})

@app.route('/api/export/cadastro/<cpf>/pdf', methods=['GET'])
@requires_auth
def exportar_cadastro_pdf(cpf):
    cadastro = Cadastro.query.get(cpf)
    if not cadastro:
        return "Cadastro não encontrado", 404

    temp_photo_path = None
    if cadastro.foto_segurado:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp:
            temp.write(cadastro.foto_segurado)
            temp_photo_path = temp.name

    pdf = CadastroPDF()
    pdf.set_photo_path(temp_photo_path)
    pdf.add_page()

    pdf.add_section_title('Dados do Segurado')
    pdf.add_field('Nome:', cadastro.nome)
    pdf.add_field('CPF:', cadastro.cpf)
    pdf.add_field('Matrícula:', cadastro.matricula or 'N/A')
    pdf.add_field('Telefone:', cadastro.telefone)
    pdf.add_field('Email:', cadastro.email or 'N/A')
    pdf.add_field('WhatsApp:', 'Sim' if cadastro.is_whatsapp else 'Não')
    pdf.add_field('Qualidade:', cadastro.qualidade)
    pdf.add_field('Data Atendimento:', cadastro.data_atendimento.strftime('%d/%m/%Y'))
    pdf.add_field('Atendente:', cadastro.atendente_criacao)
    pdf.add_field('Informação:', cadastro.informacao or 'N/A')
    pdf.add_field('Observação:', cadastro.obs or 'N/A')

    if cadastro.tem_procurador:
        pdf.add_section_title('Dados do Procurador')
        pdf.add_field('Nome:', cadastro.procurador_nome or 'N/A')
        pdf.add_field('CPF:', cadastro.procurador_cpf or 'N/A')

    if cadastro.tem_curador:
        pdf.add_section_title('Dados do Curador')
        pdf.add_field('Nome:', cadastro.curador_nome or 'N/A')
        pdf.add_field('CPF:', cadastro.curador_cpf or 'N/A')

    if cadastro.necessita_visita_social:
        pdf.add_section_title('Dados da Visita Social')
        pdf.add_field('Status:', cadastro.status_visita or 'N/A')
        pdf.add_field('Processo:', cadastro.processo or 'N/A')
        pdf.add_field('Assunto:', cadastro.assunto_visita or 'N/A')
        pdf.add_field('Endereço:', cadastro.endereco or 'N/A')

    pdf_output = pdf.output(dest='S').encode('latin-1')

    if temp_photo_path:
        os.remove(temp_photo_path)

    return Response(pdf_output, mimetype='application/pdf', headers={'Content-Disposition': f'attachment;filename=cadastro_{cadastro.cpf}.pdf'})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Cria o utilizador administrador se não existir
        if not User.query.filter_by(username=ADMIN_USERNAME).first():
            admin_user = User(
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
                permissions={
                    "cadastro": True, "consulta": True, "editar": True, "visitas-pendentes": True,
                    "visitas-realizadas": True, "estatisticas": True, "audit": True, "usuarios": True
                }
            )
            db.session.add(admin_user)
            db.session.commit()
        app.run(host='0.0.0.0', port=5000, debug=True)

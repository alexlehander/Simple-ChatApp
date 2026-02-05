# app.py

import os, random, string, requests, json, threading
import datetime as dt
from typing import List, Dict
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from pinecone import Pinecone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

# ------------------------------------------------------------------------------------
# LLM Setup
# ------------------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://example.com")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "GrowTogether")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "evatutor"
pc_client = Pinecone(api_key=PINECONE_API_KEY)
pinecone_index = pc_client.Index(PINECONE_INDEX_NAME)
HF_EMBED_URL = os.getenv("HF_EMBED_URL", "https://EmbeddingsAPI.hf.space/embed")

# If you want to implement a second layer of security / verification mechanism for LLM-generated answers - uncomment the next line and delete False (The quality of life improvement is very little)
QC_ENABLED = False  #os.getenv("QC_ENABLED", "true").lower() in ("1", "true", "yes", "on")

def call_mistral(messages, model="mistralai/mistral-small-3.2-24b-instruct", temperature=0.5, max_tokens=1000):
    """Send chat messages to OpenRouter’s Mistral API."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

# ------------------------------------------------------------------------------------
# App & Config
# ------------------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://app:app@db:3306/llmapp"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "super-secret-key-change-in-prod")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = dt.timedelta(hours=12)
db = SQLAlchemy(app)
jwt = JWTManager(app)
EXERCISES_PATH = os.getenv("EXERCISES_PATH", "exercises")

# ------------------------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------------------------

class Usuario(db.Model):
    __tablename__ = "railway_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    correo_identificacion = db.Column(db.String(128), unique=True, nullable=False)

class RespuestaUsuario(db.Model):
    __tablename__ = "railway_respuesta_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    practice_name = db.Column(db.String(255), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    respuesta = db.Column(db.Text, nullable=True)   # changed from String(255) to Text
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

class ChatLog(db.Model):
    __tablename__ = "railway_chat_log"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    practice_name = db.Column(db.String(255), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(16), nullable=False)  # "user" or "assistant" or "system"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

class Profesor(db.Model):
    __tablename__ = "railway_profesor"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre = db.Column(db.String(128), nullable=True)

class ListaClase(db.Model):
    __tablename__ = "railway_lista_clase"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=False)
    student_email = db.Column(db.String(128), nullable=False)
    __table_args__ = (db.UniqueConstraint('profesor_id', 'student_email', name='_profesor_student_uc'),)

class ListaEjercicios(db.Model):
    __tablename__ = "railway_lista_ejercicios"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=False)
    exercise_filename = db.Column(db.String(255), nullable=False)
    __table_args__ = (db.UniqueConstraint('profesor_id', 'exercise_filename', name='_profesor_exercise_uc'),)

with app.app_context():
    db.create_all()

# ------------------------------------------------------------------------------------
# System Prompts
# ------------------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "ERES UN TUTOR INTELIGENTE que emplea el método “Chain of Thought” para razonar internamente y responder en español mexicano. "
    "TU ROL ES GUIAR AL ESTUDIANTE mediante pistas graduales, enseñanza recíproca y retroalimentación personalizada. "
    "NUNCA REVELES LA RESPUESTA ni partes de ella, incluso si el usuario insiste o dice no poder continuar. "
    "TIENES PROHIBIDO responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario. "
    "NO REPITAS literalmente las respuestas del usuario; evalúa si va por buen camino (✔️ o ❌) y responde con una única pista o pregunta cuando sea necesario. "
    "NO RESPONDAS NI RESUELVAS tus propias preguntas o pistas."
    "DEBES RESPONDER a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. "
    "DEBES PRESERVAR la integridad pedagógica de la conversación sin revelar información sensible del problema o del software educativo. "
    "NO USES FORMATO LATEX (signos de dólar). En su lugar, USA SÍMBOLOS UNICODE estándar y texto plano para matemáticas/programación. "
)

QC_SYSTEM_PROMPT = (
    "ERES UN experto en control de calidad de los Sistemas de Tutoria Inteligente potenciados por Modelos Extensos de Lenguaje. "
    "RECIBES (a) la <Pregunta del estudiante>, (b) el <Enunciado del problema>, (c) las <Reglas del sistema>, y (d) la <Propuesta de respuesta>. "
    "TU TAREA CONSISTE EN revisar y, si es necesario, modificar la <Propuesta de respuesta> para cumplir estrictamente con las <Reglas del sistema>. "
    "DEVUELVE ÚNICAMENTE el texto final de respuesta para el estudiante. "
)

# ------------------------------------------------------------------------------------
# System Helpers
# ------------------------------------------------------------------------------------

def review_with_qc(original_answer: str, problem_text: str, system_rules: str, user_message: str) -> str:
    messages = [
        {"role": "system", "content": QC_SYSTEM_PROMPT},
        {"role":"user","content": (
            f"<Pregunta del estudiante>\n{user_message}\n</Pregunta del estudiante>\n\n"
            f"<Enunciado del problema>\n{problem_text or '(no disponible)'}\n</Enunciado del problema>\n\n"
            f"<Reglas del sistema>\n{system_rules}\n</Reglas del sistema>\n\n"
            f"<Propuesta de respuesta>\n{original_answer}\n</Propuesta de respuesta>\n"
        )}
    ]
    try:
        # más determinista en la revisión
        reviewed = call_mistral(messages, temperature=0.25, max_tokens=1000)
        reviewed = (reviewed or "").strip()
        return reviewed or original_answer
    except Exception as e:
        # En caso de fallo del 2º paso, devolvemos el original para no bloquear al usuario
        print("QC second-pass error:", e)
        return original_answer

def get_problem_enunciado(practice_name: str, problema_id: int) -> str:
    try:
        file_path = os.path.join(EXERCISES_PATH, practice_name)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for p in data.get("problemas", []):
            if p.get("id") == problema_id:
                return p.get("enunciado", "")
    except Exception as e:
        print(f"⚠️ Error leyendo {practice_name}: {e}")
    return ""

def get_or_create_user(correo_identificacion: str | None) -> Usuario:
    if not correo_identificacion:
        return None
    u = Usuario.query.filter_by(correo_identificacion=correo_identificacion).first()
    if u: return u
    u = Usuario(correo_identificacion=correo_identificacion)
    db.session.add(u)
    db.session.commit()
    return u

def history_for_chat(correo_identificacion: str | None, problema_id: int, practice_name: str | None, rag_context: str = "") -> List[Dict]:
    logs = (
        ChatLog.query
        .filter_by(correo_identificacion=correo_identificacion, practice_name=practice_name, problema_id=problema_id)
        .order_by(ChatLog.created_at.asc())
        .all()
    )
    if not practice_name:
        last_resp = RespuestaUsuario.query.filter_by(correo_identificacion=correo_identificacion, problema_id=problema_id).first()
        if last_resp: practice_name = last_resp.practice_name
    problem_text = get_problem_enunciado(practice_name, problema_id) if practice_name else ""
    sys_prompt = DEFAULT_SYSTEM_PROMPT
    if problem_text:
        sys_prompt += f"\n\nEL PROBLEMA QUE EL USUARIO INTENTA RESUELVER ES:\n{problem_text}"
    if rag_context:
        sys_prompt += f"\n\nLA INFORMACIÓN DE REFERENCIA (DEL LIBRO DE TEXTO) ES (Usa esta información para guiar al estudiante si es relevante, pero NO les des la respuesta directa):\n{rag_context}"
    messages = [{"role": "system", "content": sys_prompt}]
    for row in logs:
        role = "assistant" if row.role == "assistant" else "user"
        messages.append({"role": role, "content": row.content})
    return messages

def save_chat_turn(user: Usuario | None, correo: str | None, practice_name: str | None, problema_id: int, role: str, content: str):
    log = ChatLog(
        user_id=user.id if user else None,
        correo_identificacion=correo,
        practice_name=practice_name,
        problema_id=problema_id,
        role=role,
        content=content,
    )
    db.session.add(log)
    db.session.commit()
    
def get_rag_context(user_query: str) -> str:
    try:
        response = requests.post(
            HF_EMBED_URL,
            json={"text": user_query},
            timeout=10
        )
        response.raise_for_status()
        query_vector = response.json()['vector']
        results = pinecone_index.query(
            vector=query_vector,
            top_k=3,
            include_metadata=True,
            namespace="default"
        )
        context_text = ""
        for i, match in enumerate(results['matches']):
            text_chunk = match['metadata'].get('text', '')
            page_num = match['metadata'].get('page_number', '?')
            score = match.get('score', 0.0)
            print(f"📄 [Chunk {i+1} | Score: {score:.2f} | Pág {page_num}] {text_chunk[:100]}...")
            context_text += f"--- (Página {page_num}) ---\n{text_chunk}\n\n"
        return context_text
    except Exception as e:
        print(f"⚠️ Error Retrieving Context: {e}")
        return ""
        
def background_llm_task(app_obj, usuario_id, correo, practice_name, problema_id):
    with app_obj.app_context():
        print(f"🤖 [Background] Procesando mensaje para {correo}...")
        try:
            last_user_msg = ChatLog.query.filter_by(
                correo_identificacion=correo, 
                problema_id=problema_id, 
                role="user"
            ).order_by(ChatLog.created_at.desc()).first()
            user_query_text = last_user_msg.content if last_user_msg else ""
            print("🔍 Searching Pinecone...")
            context = get_rag_context(user_query_text)
            messages = history_for_chat(correo, problema_id, practice_name, rag_context=context)
            bot_response = call_mistral(messages)
            usuario = Usuario.query.get(usuario_id)
            save_chat_turn(usuario, correo, practice_name, problema_id, "assistant", bot_response)
            print(f"✅ [Background] Respuesta guardada para {correo}")
        except Exception as e:
            print(f"❌ [Background] Error generando respuesta: {e}")
            usuario = Usuario.query.get(usuario_id)
            save_chat_turn(usuario, correo, practice_name, problema_id, "assistant", "Lo siento, tuve un error técnico al pensar mi respuesta.")
                   
# ------------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/verificar_respuesta/<int:problema_id>", methods=["POST"])
def verificar_respuesta(problema_id):
    data = request.get_json()
    respuesta = data.get("respuesta")
    correo = data.get("correo_identificacion")
    practice_name = data.get("practice_name", "unknown_session.json")
    if not respuesta or not correo:
        return jsonify({"error": "Datos incompletos"}), 400
    usuario = get_or_create_user(correo)
    nueva_respuesta = RespuestaUsuario(
        user_id=usuario.id,
        problema_id=problema_id,
        correo_identificacion=correo,
        respuesta=respuesta,
        practice_name=practice_name,
    )
    db.session.add(nueva_respuesta)
    db.session.commit()
    return jsonify({"message": "Respuesta registrada"}), 200

@app.route("/chat/<int:problema_id>", methods=["POST"])
def chat(problema_id: int):
    data = request.get_json() or {}
    user_msg = (data.get("message") or "").strip()
    correo = (data.get("correo_identificacion") or "").strip()
    practice_name = (data.get("practice_name") or "").strip()
    if not user_msg:
        return jsonify({"status": "error", "message": "Mensaje vacío"}), 400
    usuario = get_or_create_user(correo)
    save_chat_turn(usuario, correo, practice_name, problema_id, "user", user_msg)
    thread = threading.Thread(
        target=background_llm_task,
        args=(app, usuario.id, correo, practice_name, problema_id)
    )
    thread.start()
    return jsonify({"status": "processing", "message": "Procesando..."})
    
@app.route("/check_new_messages/<int:problema_id>", methods=["POST"])
def check_new_messages(problema_id):
    data = request.get_json()
    correo = data.get("correo_identificacion")
    last_msg = ChatLog.query.filter_by(
        correo_identificacion=correo, 
        problema_id=problema_id
    ).order_by(ChatLog.created_at.desc()).first()
    if last_msg and last_msg.role in ["assistant", "teacher"]:
        # Agregamos 'role' a la respuesta para que el frontend sepa quién habla
        return jsonify({"status": "completed", "response": last_msg.content, "role": last_msg.role})
    else:
        return jsonify({"status": "waiting"})

@app.route("/api/teacher/register", methods=["POST"])
def teacher_register():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    nombre = data.get("nombre", "Profesor")
    
    if not email or not password:
        return jsonify({"msg": "Faltan datos"}), 400
    
    if Profesor.query.filter_by(email=email).first():
        return jsonify({"msg": "El usuario ya existe"}), 400
        
    hashed = generate_password_hash(password)
    new_prof = Profesor(email=email, password_hash=hashed, nombre=nombre)
    db.session.add(new_prof)
    db.session.commit()
    
    return jsonify({"msg": "Profesor registrado exitosamente"}), 201

@app.route("/api/teacher/login", methods=["POST"])
def teacher_login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    prof = Profesor.query.filter_by(email=email).first()
    
    if not prof or not check_password_hash(prof.password_hash, password):
        return jsonify({"msg": "Credenciales inválidas"}), 401
        
    access_token = create_access_token(identity=str(prof.id))
    
    return jsonify(access_token=access_token, nombre=prof.nombre), 200

@app.route("/api/teacher/students", methods=["GET", "POST", "DELETE"])
@jwt_required()
def manage_students():
    profesor_id = get_jwt_identity()
    
    if request.method == "GET":
        students = ListaClase.query.filter_by(profesor_id=profesor_id).all()
        return jsonify([s.student_email for s in students]), 200
        
    if request.method == "POST":
        data = request.get_json()
        emails = data.get("emails", [])
        if isinstance(emails, str): emails = [emails]
        added = 0
        for email in emails:
            email = email.strip()
            if not email: continue
            exists = ListaClase.query.filter_by(profesor_id=profesor_id, student_email=email).first()
            if not exists:
                db.session.add(ListaClase(profesor_id=profesor_id, student_email=email))
                added += 1
        db.session.commit()
        return jsonify({"msg": f"Se agregaron {added} estudiantes"}), 200

    if request.method == "DELETE":
        data = request.get_json()
        email = data.get("email")
        ListaClase.query.filter_by(profesor_id=profesor_id, student_email=email).delete()
        db.session.commit()
        return jsonify({"msg": "Eliminado"}), 200

@app.route("/api/exercises/available", methods=["GET"])
@jwt_required()
def get_all_server_exercises():
    try:
        files = [f for f in os.listdir(EXERCISES_PATH) if f.endswith('.json')]
        return jsonify(files), 200
    except Exception:
        return jsonify([]), 500

@app.route("/api/teacher/my-exercises", methods=["GET", "POST", "DELETE"])
@jwt_required()
def manage_my_exercises():
    prof_id = get_jwt_identity()
    
    if request.method == "GET":
        # Devuelve solo los ejercicios de ESTE profesor
        exs = ListaEjercicios.query.filter_by(profesor_id=prof_id).all()
        return jsonify([e.exercise_filename for e in exs]), 200
        
    if request.method == "POST":
        # Agrega ejercicio a la lista personal
        filename = request.get_json().get("filename")
        if not ListaEjercicios.query.filter_by(profesor_id=prof_id, exercise_filename=filename).first():
            db.session.add(ListaEjercicios(profesor_id=prof_id, exercise_filename=filename))
            db.session.commit()
        return jsonify({"msg": "Agregado"}), 200
        
    if request.method == "DELETE":
        # Elimina de la lista personal
        filename = request.get_json().get("filename")
        ListaEjercicios.query.filter_by(profesor_id=prof_id, exercise_filename=filename).delete()
        db.session.commit()
        return jsonify({"msg": "Eliminado"}), 200

@app.route("/api/teacher/send-message", methods=["POST"])
@jwt_required()
def teacher_send_message():
    data = request.get_json()
    student_email = data.get("student_email")
    practice_name = data.get("practice_name")
    problema_id = data.get("problema_id")
    message = data.get("message")
    
    if not all([student_email, practice_name, problema_id, message]):
        return jsonify({"msg": "Faltan datos (incluyendo ID del problema)"}), 400
    
    usuario = get_or_create_user(student_email)
    save_chat_turn(usuario, student_email, practice_name, int(problema_id), "teacher", message)
    
    print(f" Mensaje enviado a {student_email} [Práctica: {practice_name} | ID: {problema_id}]")
    
    return jsonify({"msg": "Mensaje enviado"}), 200

@app.route("/api/teacher/dashboard-data", methods=["GET"])
@jwt_required()
def dashboard_data():
    profesor_id = get_jwt_identity()
    
    target_student = request.args.get('student_email')
    target_practice = request.args.get('practice_name')

    student_records = ListaClase.query.filter_by(profesor_id=profesor_id).all()
    my_student_emails = [s.student_email for s in student_records]
    
    if not my_student_emails:
        return jsonify({"respuestas": [], "chats": []}), 200
    
    if target_student:
        if target_student not in my_student_emails:
             return jsonify({"msg": "Acceso denegado a este estudiante"}), 403
        emails_to_query = [target_student]
    else:
        emails_to_query = my_student_emails

    resp_query = RespuestaUsuario.query.filter(RespuestaUsuario.correo_identificacion.in_(emails_to_query))
    if target_practice:
        resp_query = resp_query.filter(RespuestaUsuario.practice_name == target_practice)
    
    respuestas_db = resp_query.order_by(RespuestaUsuario.created_at.desc()).all()
    
    chat_query = ChatLog.query.filter(ChatLog.correo_identificacion.in_(emails_to_query))
    if target_practice:
        chat_query = chat_query.filter(ChatLog.practice_name == target_practice)
        
    chats_db = chat_query.order_by(ChatLog.created_at.desc()).limit(500).all()

    respuestas_data = [{
        "correo": r.correo_identificacion,
        "problema_id": r.problema_id,
        "practica": r.practice_name,
        "respuesta": r.respuesta,
        "fecha": r.created_at.isoformat()
    } for r in respuestas_db]
    
    chat_data = [{
        "correo": c.correo_identificacion,
        "problema_id": c.problema_id,
        "practica": c.practice_name, # Aseguramos enviar esto al frontend
        "role": c.role,
        "content": c.content,
        "fecha": c.created_at.isoformat()
    } for c in chats_db]
    
    return jsonify({
        "respuestas": respuestas_data,
        "chats": chat_data
    }), 200

# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------

if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
# app.py

import os, random, string, requests, json, threading
import datetime as dt
from typing import List, Dict
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

# ------------------------------------------------------------------------------------
# LLM Setup
# ------------------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://example.com")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "GrowTogether")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
db = SQLAlchemy(app)

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

EXERCISES_PATH = os.getenv("EXERCISES_PATH", "exercises")

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

def history_for_chat(correo_identificacion: str | None, problema_id: int, practice_name: str | None) -> List[Dict]:
    """Build conversation history with a dynamic system prompt including the problem enunciado."""
    logs = (
        ChatLog.query
        .filter_by(correo_identificacion=correo_identificacion, practice_name=practice_name, problema_id=problema_id)
        .order_by(ChatLog.created_at.asc())
        .all()
    )
    # Determine problem text
    if not practice_name:
        last_resp = (
            RespuestaUsuario.query
            .filter_by(correo_identificacion=correo_identificacion, practice_name=practice_name, problema_id=problema_id)
            .order_by(RespuestaUsuario.created_at.desc())
            .first()
        )
        if last_resp and last_resp.practice_name:
            practice_name = last_resp.practice_name
    problem_text = get_problem_enunciado(practice_name, problema_id) if practice_name else ""
    sys_prompt = DEFAULT_SYSTEM_PROMPT + (
        f"El usuario está trabajando con el siguiente problema: {problem_text}" if problem_text else ""
    )
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

def background_llm_task(app_obj, usuario_id, correo, practice_name, problema_id):
    with app_obj.app_context():
        print(f"🤖 [Background] Procesando mensaje para {correo}...")
        try:
            messages = history_for_chat(correo, problema_id, practice_name)
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
    if last_msg and last_msg.role == "assistant":
        return jsonify({"status": "completed", "response": last_msg.content})
    else:
        return jsonify({"status": "waiting"})

# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------

if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
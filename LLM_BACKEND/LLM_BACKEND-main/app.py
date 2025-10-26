# app.py
# Backend for single-condition, open-ended answering flow
import os
import random
import string
import requests
import json
import datetime as dt
from typing import List, Dict

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

# ------------------------------------------------------------------------------------
# Mistral / OpenRouter setup
# ------------------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://example.com")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "GrowTogether")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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

# DB URL via env; default matches docker-compose.yml
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://app:app@db:3306/llmapp"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# OpenAI key (env only; no hard-coded secrets)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# ------------------------------------------------------------------------------------
# Data Model (table names align with your SQL dumps)
# ------------------------------------------------------------------------------------
class Usuario(db.Model):
    __tablename__ = "railway_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    correo_identificacion = db.Column(db.String(128), unique=True, nullable=False)

class RespuestaUsuario(db.Model):
    __tablename__ = "railway_respuesta_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    practice_name = db.Column(db.String(255), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    respuesta = db.Column(db.Text, nullable=True)   # changed from String(255) to Text
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

class ChatLog(db.Model):
    __tablename__ = "railway_chat_log"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(16), nullable=False)  # "user" or "assistant" or "system"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

with app.app_context():
    db.create_all()

    # --- Auto-migrate: add practice_name column ---
    try:
        exists = db.session.execute(db.text("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_NAME = 'railway_respuesta_usuario'
            AND COLUMN_NAME = 'practice_name'
        """)).scalar()

        if not exists:
            print("⚙️ Adding 'practice_name' column...")
            db.session.execute(db.text("""
                ALTER TABLE railway_respuesta_usuario
                ADD COLUMN practice_name VARCHAR(255) NULL
            """))
            db.session.commit()
            print("✔ Column 'practice_name' added successfully")
        else:
            print("↪ Column 'practice_name' already present, skipping")
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Skipping add 'practice_name': {e}")

    
    # --- Auto-migrate: respuesta -> TEXT (run only once) ---
    try:
        dtype = db.session.execute(db.text(
            "SELECT DATA_TYPE "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'railway_respuesta_usuario' "
            "AND COLUMN_NAME = 'respuesta'"
        )).scalar()

        if dtype == "varchar":
            db.session.execute(db.text(
                "ALTER TABLE railway_respuesta_usuario "
                "MODIFY COLUMN respuesta TEXT"
            ))
            db.session.commit()
            print("✔ Migrated railway_respuesta_usuario.respuesta to TEXT")
        else:
            print(f"↪ respuesta already {dtype}, skipping")
    except Exception as e:
        db.session.rollback()
        print("⚠️ Skipping respuesta TEXT migration:", e)

    # --- Auto-migrate: drop obsolete 'correcta' column ---
    try:
        exists = db.session.execute(db.text("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'railway_respuesta_usuario'
              AND COLUMN_NAME = 'correcta'
        """)).scalar()

        if exists:
            print("⚙️ Dropping obsolete column 'correcta' ...")
            db.session.execute(db.text("ALTER TABLE railway_respuesta_usuario DROP COLUMN correcta"))
            db.session.commit()
            print("✔ Column 'correcta' dropped successfully")
        else:
            print("↪ Column 'correcta' already absent, skipping")
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Skipping drop 'correcta': {e}")

    # --- Auto-migrate: rename codigo_identificacion → correo_identificacion (run only once) ---
    try:
        for table in ["railway_usuario", "railway_respuesta_usuario", "railway_chat_log"]:
            old_col_exists = db.session.execute(db.text(f"""
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = '{table}'
                AND COLUMN_NAME = 'codigo_identificacion'
            """)).scalar()
            new_col_exists = db.session.execute(db.text(f"""
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = '{table}'
                AND COLUMN_NAME = 'correo_identificacion'
            """)).scalar()
            if old_col_exists and not new_col_exists:
                print(f"⚙️ Renaming codigo_identificacion → correo_identificacion in {table}...")
                db.session.execute(db.text(f"""
                    ALTER TABLE {table}
                    CHANGE codigo_identificacion correo_identificacion VARCHAR(128) NULL
                """))
                db.session.commit()
                print(f"✔ {table}: renamed successfully")
            else:
                print(f"↪ {table}: already migrated, skipping")
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Skipping rename migration: {e}")

# ------------------------------------------------------------------------------------
# Problem bank (18 open-ended problems; replace texts with yours if needed)
# ------------------------------------------------------------------------------------
# If you have your real enunciados in code already, replace the strings below.

DEFAULT_SYSTEM_PROMPT = (
    "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. "
    "BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario. "
    "TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario. "
    "RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. "
    "DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. "
    "Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. "
)

EXERCISES_PATH = os.getenv("EXERCISES_PATH", "exercises")

# ------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------
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
        # still allow an anonymous row, but with NULL email
        u = Usuario(correo_identificacion=None)
        db.session.add(u)
        db.session.commit()
        return u
    u = Usuario.query.filter_by(correo_identificacion=correo_identificacion).first()
    if u:
        return u
    u = Usuario(correo_identificacion=correo_identificacion)
    db.session.add(u)
    db.session.commit()
    return u

def history_for_chat(correo_identificacion: str | None, problema_id: int, practice_name: str | None = None) -> List[Dict]:
    """Build conversation history with a dynamic system prompt including the problem enunciado."""
    logs = (
        ChatLog.query
        .filter_by(correo_identificacion=correo_identificacion, problema_id=problema_id)
        .order_by(ChatLog.created_at.asc())
        .all()
    )

    # Determine problem text
    if not practice_name:
        last_resp = (
            RespuestaUsuario.query
            .filter_by(problema_id=problema_id)
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

def save_chat_turn(user: Usuario | None, correo: str | None, problema_id: int, role: str, content: str):
    log = ChatLog(
        user_id=user.id if user else None,
        correo_identificacion=correo,
        problema_id=problema_id,
        role=role,
        content=content,
    )
    db.session.add(log)
    db.session.commit()

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
    """
    Simple tutoring chat tied to a problem id.
    Uses a single prompt set (no condition branching).
    """
    data = request.get_json() or {}
    user_msg = (data.get("message") or "").strip()
    correo_identificacion = (data.get("correo_identificacion") or "").strip()
    practice_name = (data.get("practice_name") or "").strip()

    if not user_msg:
        return jsonify({"response": "¿Puedes escribir tu mensaje?"})

    usuario = get_or_create_user(correo_identificacion or None)

    # Save user's turn
    save_chat_turn(usuario, correo_identificacion or None, problema_id, "user", user_msg)

    # Build message history (system + prior turns)
    messages = history_for_chat(correo_identificacion or None, problema_id, practice_name)

    # Append current user message (again for the actual call)
    messages.append({"role": "user", "content": user_msg})

    # If we don't have an API key, return a graceful fallback
    if not OPENROUTER_API_KEY:
        assistant_text = (
            "Gracias por tu mensaje. En este momento no puedo contactar al tutor automático. "
            "Intenta explicar tu razonamiento y da el siguiente paso en el problema."
        )
        # ➜ Guardar turno del asistente y responder
        save_chat_turn(usuario, correo_identificacion or None, problema_id, "assistant", assistant_text)
        return jsonify({"response": assistant_text})
    else:
        try:
            assistant_text = call_mistral(messages)
        except Exception as e:
            print("Error contacting Mistral:", e)
            assistant_text = (
                "He tenido un problema técnico para generar una respuesta en este momento. "
                "Mientras tanto, intenta descomponer el problema en pasos más pequeños y explícame tu siguiente idea."
            )

        # Save assistant's turn
        save_chat_turn(usuario, correo_identificacion or None, problema_id, "assistant", assistant_text)
        return jsonify({"response": assistant_text})

# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)

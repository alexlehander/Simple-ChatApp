import gevent.monkey
gevent.monkey.patch_all()
import pandas as pd
import datetime as dt
import os, random, string, requests, json, threading, re, traceback, warnings, pdfplumber, gevent, pytesseract
from io import BytesIO
from typing import List, Dict
from flask import Flask, jsonify, request, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from sqlalchemy import text, inspect, func
from flask_cors import CORS
from pinecone import Pinecone
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt, decode_token
from zoneinfo import ZoneInfo
from pdf2image import convert_from_bytes
warnings.filterwarnings("ignore", category=DeprecationWarning)

def hora_ensenada():
    return dt.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None)

def encontrar_raiz_proyecto(marcador="assets"):
    ruta_actual = os.path.dirname(os.path.abspath(__file__))
    while True:
        if marcador in os.listdir(ruta_actual):
            return ruta_actual
        ruta_padre = os.path.dirname(ruta_actual)
        if ruta_padre == ruta_actual:
            raise FileNotFoundError(f"No se encontró la carpeta raíz conteniendo '{marcador}'")
        ruta_actual = ruta_padre
try:
    ROOT_DIR = encontrar_raiz_proyecto("assets") 
    ASSETS_PATH = os.path.join(ROOT_DIR, "assets")
    EXERCISES_PATH = os.path.join(ROOT_DIR, "exercises")
    print(f"✅ Raíz del proyecto encontrada en: {ROOT_DIR}")
except Exception as e:
    print(f"⚠️ Advertencia: {e}. Usando rutas relativas locales.")
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSETS_PATH = "assets"
    EXERCISES_PATH = "exercises"

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
SEMAPHORE_WINDOW_MINUTES = 5
RED_FLAG_INTENTS = ["Demanda por Respuesta", "Comportamiento Negativo"]
YELLOW_FLAG_INTENTS = ["Fuera del Tema", "Expresion de Incomprension"]
RED_THRESHOLD = 2    # How many red flags in the window trigger RED state
YELLOW_THRESHOLD = 2 # How many yellow flags trigger YELLOW state

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

    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

# ------------------------------------------------------------------------------------
# App & Config
# ------------------------------------------------------------------------------------

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config["JWT_QUERY_STRING_NAME"] = "jwt"
CORS(app)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://app:app@db:3306/llmapp"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "super-secret-key-change-in-prod")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = dt.timedelta(hours=12)
app.config["JWT_TOKEN_LOCATION"] = ["headers", "query_string"]
db = SQLAlchemy(app)
jwt = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ------------------------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------------------------

class Usuario(db.Model):
    __tablename__ = "railway_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    correo_identificacion = db.Column(db.String(128), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre = db.Column(db.String(128), nullable=True)

class RespuestaUsuario(db.Model):
    __tablename__ = "railway_respuesta_usuario"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    practice_name = db.Column(db.String(255), nullable=True)
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    respuesta = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=hora_ensenada)
    llm_score = db.Column(db.Float, nullable=True)
    llm_comment = db.Column(db.Text, nullable=True)
    teacher_score = db.Column(db.Float, nullable=True)
    teacher_comment = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending")

class ChatLog(db.Model):
    __tablename__ = "railway_chat_log"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("railway_usuario.id"), nullable=True)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    practice_name = db.Column(db.String(255), nullable=True)
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=True)
    problema_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=hora_ensenada)

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
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=False)
    exercise_filename = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint('profesor_id', 'exercise_filename', name='_profesor_exercise_uc'),)

class AnalisisInteraccion(db.Model):
    __tablename__ = "railway_analisis_interaccion"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("railway_chat_log.id"), nullable=False)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    intent = db.Column(db.String(50), nullable=True)
    dimension = db.Column(db.String(50), nullable=True)
    color_asignado = db.Column(db.String(50), default="green")
    created_at = db.Column(db.DateTime, default=hora_ensenada)

class ReporteDesempeno(db.Model):
    __tablename__ = "railway_reporte_desempeno"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_email = db.Column(db.String(128), nullable=False)
    practice_name = db.Column(db.String(255), nullable=False)
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=True)
    perfil_estudiante = db.Column(db.String(50), nullable=True)
    persistencia = db.Column(db.String(50), nullable=True)
    diagnostico_general = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=hora_ensenada)

class ReporteSesionVivo(db.Model):
    __tablename__ = "railway_reporte_sesion_vivo"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    report_data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=hora_ensenada)
    
class Grupo(db.Model):
    __tablename__ = "railway_grupo"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=False)
    nombre = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=hora_ensenada)

class GrupoEstudiante(db.Model):
    __tablename__ = "railway_grupo_estudiante"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    grupo_id = db.Column(db.Integer, db.ForeignKey("railway_grupo.id"), nullable=False)
    student_email = db.Column(db.String(128), nullable=False)

class GrupoTarea(db.Model):
    __tablename__ = "railway_grupo_tarea"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=True)
    grupo_id = db.Column(db.Integer, db.ForeignKey("railway_grupo.id"), nullable=False)
    exercise_filename = db.Column(db.String(255), nullable=False)

class Practica(db.Model):
    __tablename__ = "railway_practica"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("railway_profesor.id"), nullable=True) # Null = Tarea global del sistema
    titulo = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    max_time = db.Column(db.Integer, default=60)
    rubricas = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=hora_ensenada)

class Problema(db.Model):
    __tablename__ = "railway_problema"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    practica_id = db.Column(db.Integer, db.ForeignKey("railway_practica.id"), nullable=False)
    numero_ejercicio = db.Column(db.Integer, nullable=False)
    enunciado = db.Column(db.Text, nullable=False)

# ------------------------------------------------------------------------------------
# System Prompts
# ------------------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "ERES UN TUTOR INTELIGENTE que emplea el método “Chain of Thought” para razonar internamente y responder en español mexicano. "
    "TU ROL ES GUIAR AL ESTUDIANTE mediante pistas graduales, enseñanza recíproca y retroalimentación personalizada. "
    "NUNCA REVELES LA RESPUESTA ni partes de ella, incluso si el usuario insiste o dice no poder continuar. "
    "TIENES PROHIBIDO responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario. "
    "NO REPITAS literalmente las respuestas del usuario; evalúa si va por buen camino y responde con una única pista o pregunta cuando sea necesario. "
    "NO RESPONDAS NI RESUELVAS tus propias preguntas o pistas."
    "DEBES RESPONDER a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. "
    "DEBES PRESERVAR la integridad pedagógica de la conversación sin revelar información sensible del problema o del software educativo. "
    "NO USES FORMATO LATEX (signos de dólar). En su lugar, usa símbolos UNICODE estándar y texto plano para escribir. "
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
    # practice_name ahora actúa como un "puente" que recibe el ID (ej. "15")
    try:
        pid = int(practice_name)
        prob = Problema.query.filter_by(practica_id=pid, numero_ejercicio=problema_id).first()
        if prob: return prob.enunciado
    except ValueError:
        # Fallback de seguridad para tareas históricas
        prac = Practica.query.filter_by(titulo=practice_name).first()
        if prac:
            prob = Problema.query.filter_by(practica_id=prac.id, numero_ejercicio=problema_id).first()
            if prob: return prob.enunciado
    return "Enunciado no disponible."

def get_or_create_user(correo_identificacion: str | None) -> Usuario:
    if not correo_identificacion:
        return None
    u = Usuario.query.filter_by(correo_identificacion=correo_identificacion).first()
    if u:
        return u
    try:
        u = Usuario(correo_identificacion=correo_identificacion)
        db.session.add(u)
        db.session.commit()
        return u
    except Exception:
        db.session.rollback()
        return Usuario.query.filter_by(correo_identificacion=correo_identificacion).first()

def history_for_chat(correo_identificacion: str | None, problema_id: int, practice_name: str | None, rag_context: str = "") -> List[Dict]:
    limite_tiempo = hora_ensenada() - dt.timedelta(hours=24)
    logs = (
        ChatLog.query
        .filter_by(correo_identificacion=correo_identificacion, practice_name=practice_name, problema_id=problema_id)
        .filter(ChatLog.created_at >= limite_tiempo)
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
    pid = None
    try: pid = int(practice_name)
    except (ValueError, TypeError): pass
        
    log = ChatLog(
        user_id=user.id if user else None,
        correo_identificacion=correo,
        practice_name=practice_name,
        practica_id=pid,
        problema_id=problema_id,
        role=role,
        content=content,
    )
    db.session.add(log)
    db.session.commit()
    return log.id
    
def get_rag_context(user_query: str) -> str:
    return ""
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
                practice_name=practice_name,
                problema_id=problema_id, 
                role="user"
            ).order_by(ChatLog.id.desc()).first()
            user_query_text = last_user_msg.content if last_user_msg else ""
            context = ""
            if len(user_query_text.strip()) > 15:
                print("🔍 Searching Pinecone...")
                context = get_rag_context(user_query_text)
            messages = history_for_chat(correo, problema_id, practice_name, rag_context=context)
            bot_response = call_mistral(messages)
            usuario = db.session.get(Usuario, usuario_id)
            save_chat_turn(usuario, correo, practice_name, problema_id, "assistant", bot_response)
            socketio.emit('nuevo_mensaje_bot', {
                'correo': correo,
                'problema_id': problema_id,
                'role': 'assistant',
                'content': bot_response
            })
            print(f"✅ [Background] Respuesta guardada para {correo}")
        except Exception as e:
            print(f"❌ [Background] Error generando respuesta: {e}")
            usuario = db.session.get(Usuario, usuario_id)
            save_chat_turn(usuario, correo, practice_name, problema_id, "assistant", "Lo siento, tuve un error técnico al pensar mi respuesta.")

def get_exercise_metadata(filename):
    try:
        pid = int(filename)
        p = Practica.query.get(pid)
    except ValueError:
        p = Practica.query.filter_by(titulo=filename).first()
        
    if p:
        probs = Problema.query.filter_by(practica_id=p.id).order_by(Problema.numero_ejercicio).all()
        return {
            "filename": str(p.id),
            "title": p.titulo,
            "description": p.descripcion,
            "max_time": p.max_time * 60,
            "num_problems": len(probs),
            "problemas": [{"id": pr.numero_ejercicio, "enunciado": pr.enunciado} for pr in probs]
        }
    return {
        "filename": filename, "title": "Práctica Desconocida", "description": "Error leyendo de BD.", 
        "max_time": 0, "num_problems": 0
    }

def analyze_interaction_semaphore(chat_log_id, user_message, correo, prog_pct):
    with app.app_context():
        sys_prompt = (
            "Eres un experto en Learning Analytics. Clasifica la interacción del estudiante.\n"
            "CATEGORÍAS:\n"
            "1. Peticion de Ayuda (Productivo)\n"
            "2. Busqueda Conceptual (Productivo)\n"
            "3. Confirmacion de Razonamiento (Productivo)\n"
            "4. Solicitud de Ejemplo (Productivo)\n"
            "5. Calculo u Operacion (Productivo)\n"
            "6. Expresion de Incomprension (Improductivo - YELLOW FLAG)\n"
            "7. Fuera del Tema (Improductivo - YELLOW FLAG)\n"
            "8. Demanda por Respuesta (Improductivo - RED FLAG)\n"
            "9. Comportamiento Negativo (Improductivo - RED FLAG)\n"
            "10. Otro (Neutro)\n\n"
            "Devuelve SOLO un JSON: {\"intent\": \"...\", \"dimension\": \"Productivo/Improductivo/Neutro\"}"
        )
        try:
            response_text = call_mistral([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_message}
            ], temperature=0.2, max_tokens=100)
            try:
                data = json.loads(response_text)
            except:
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                data = json.loads(match.group(0)) if match else {"intent": "Otro", "dimension": "Neutro"}
            intent = data.get("intent", "Otro")
            color = "green"
            if intent in ["Demanda por Respuesta", "Comportamiento Negativo"]:
                color = "red"
            elif intent in ["Expresion de Incomprension", "Fuera del Tema"]:
                since = hora_ensenada() - dt.timedelta(minutes=5)
                recent_issues = AnalisisInteraccion.query.filter(
                    AnalisisInteraccion.correo_identificacion == correo,
                    AnalisisInteraccion.intent.in_(["Expresion de Incomprension", "Fuera del Tema"]),
                    AnalisisInteraccion.created_at >= since
                ).count()
                if recent_issues >= 2: 
                    color = "yellow"
            intent_raw = data.get("intent", "Otro")
            dimension_safe = str(data.get("dimension", "Neutro"))[:50]          
            calculated_color = calculate_sliding_window_color(correo)
            analysis = AnalisisInteraccion(
                chat_id=chat_log_id,
                correo_identificacion=correo,
                intent=intent_raw,
                dimension=dimension_safe,
                color_asignado=calculated_color
            )
            db.session.add(analysis)
            db.session.commit()
            print(f"🚦 Semaphore ({SEMAPHORE_WINDOW_MINUTES}m window): {correo} -> {intent_raw} | State: {calculated_color}")
            socketio.emit('student_activity', {
                'type': 'chat',
                'student_email': correo,
                'status': calculated_color,
                'intent': intent_raw,
                'last_message': user_message,
                'progress_pct': prog_pct,
                'timestamp': hora_ensenada().isoformat(),
                'analysis_id': analysis.id
            })
        except Exception as e:
            print(f"❌ Error in Semaphore Analysis: {e}")
            
# 2. Automated Grading Function
def auto_grade_answer(respuesta_id, problem_text, student_answer, prog_pct):
    example_json = """{
        "calificación": 8,
        "comentario": "La lógica general es adecuada, pero el desarrollo carece de pasos intermedios y la explicación es muy superficial.",
        "rubricas": [
            {"dimension": "Exactitud de la solución", "observacion": "El resultado final de la operación coincide con el esperado."},
            {"dimension": "Completitud del procedimiento", "observacion": "Se saltó la declaración de variables y no mostró el proceso paso a paso."},
            {"dimension": "Nivel de detalle de la explicación", "observacion": "Solo indicó el resultado sin argumentar el razonamiento analítico."}
        ]
    }"""
    user_prompt = f"""
        Actúa como un profesor experto de ciencias computacionales que evalúa una práctica universitaria.
        A continuación se presenta un ejercicio realizado por el estudiante.
        El bloque contiene la **Descripción del Problema** y la **Respuesta del Estudiante**.

        Tu tarea consiste en:
        1. Leer la descripción del problema para entender qué se pedía.
        2. Evaluar la respuesta basándote EXCLUSIVAMENTE en estas 3 dimensiones:
           - Exactitud de la solución: ¿Es correcta la respuesta final conceptual o matemáticamente?
           - Completitud del procedimiento: ¿El estudiante mostró y desarrolló todos los pasos técnicos necesarios?
           - Nivel de detalle de la explicación: ¿El estudiante justificó adecuadamente su razonamiento?
        3. Asignar una calificación global (0-10) basada en las dimensiones anteriores.
        4. Redactar un 'comentario' general corto, que se le mostrara posteriormente al estudiante junto con la calificación del profesor.
        5. Generar una 'observacion' específica y detallada para cada una de las 3 'rubricas'.

        Usa esta rúbrica para asignar la calificación y guiar tu comentario (puedes usar tambien numeros impares si la respuesta proporcionada por el estudiante cae entre 2 items):
        - 10: Solución correcta, cuenta con el procedimiento completo y una explicación exhaustiva.
        - 8: Solución correcta y explicación exhaustiva, pero el procedimiento es incomplelto.
        - 8: Solución correcta y procedimiento completo, pero la explicación no es exhaustiva.
        - 6: Solución incorecta, pero el procedimiento es completo y la explicación es exhaustiva.
        - 4: Solución incorecta, procedimiento incompleto pero la explicación es exhaustiva.
        - 4: Solución incorecta, explicación no exhaustiva pero el procedimiento es completo.
        - 2: Solución incorecta, explicación no exhaustiva y procedimiento incompleto.
        - 0: Estudiante no proporciono ninguna informacion para responder este ejercicio.

        Devuelve **únicamente** un JSON válido con esta estructura:
        --- INICIO DEL EJEMPLO ---
        {example_json}
        --- FIN DEL EJEMPLO ---

        --- INICIO DE LA RESPUESTA ---
        Descripción del Problema: {problem_text}
        Respuesta del Estudiante: {student_answer}
        --- FIN DE LA RESPUESTA ---
    """

    try:
        response_text = call_mistral([
            {"role": "system", "content": "Eres un evaluador académico estricto y justo que responde solo en JSON."},
            {"role": "user", "content": user_prompt}
        ], temperature=0.2)
        
        try:
            data = json.loads(response_text)
        except:
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            data = json.loads(match.group(0)) if match else {"calificación": 0, "comentario": "Error al procesar la evaluación del LLM"}

        nota = float(data.get("calificación", data.get("score", 0)))
        comentario_completo = json.dumps(data, ensure_ascii=False)

        with app.app_context():
            resp_record = db.session.get(RespuestaUsuario, respuesta_id)
            if resp_record:
                resp_record.llm_score = nota
                resp_record.llm_comment = comentario_completo
                resp_record.status = "pending"
                db.session.commit()
                
                print(f"📝 Evaluado ID {respuesta_id}: {resp_record.llm_score}/10")
                color = "green" if nota >= 7 else "yellow" if nota >= 4 else "red"
                
                socketio.emit('student_activity', {
                    'type': 'answer',
                    'student_email': resp_record.correo_identificacion,
                    'status': color,
                    'score': nota,
                    'practice': resp_record.practice_name,
                    'problem_id': resp_record.problema_id,
                    'progress_pct': prog_pct,
                    'timestamp': hora_ensenada().isoformat(),
                    'answer_id': resp_record.id
                })
                
    except Exception as e:
        print(f"❌ Error en Auto-Grading: {e}")

# --- app.py (Helper functions section) ---
def calculate_sliding_window_color(student_email):
    """Calculates status color based on recent interaction history."""
    with app.app_context():
        since_time = hora_ensenada() - dt.timedelta(minutes=SEMAPHORE_WINDOW_MINUTES)
        recent_interactions = AnalisisInteraccion.query.filter(
            AnalisisInteraccion.correo_identificacion == student_email,
            AnalisisInteraccion.created_at >= since_time
        ).order_by(AnalisisInteraccion.created_at.desc()).all()
        
        if not recent_interactions:
            return "green"
        red_count = 0
        yellow_count = 0
        
        for interaction in recent_interactions:
            intent_lower = (interaction.intent or "").lower()
            
            if any(flag.lower() in intent_lower for flag in RED_FLAG_INTENTS):
                red_count += 1
            elif any(flag.lower() in intent_lower for flag in YELLOW_FLAG_INTENTS):
                yellow_count += 1
                
        if red_count >= RED_THRESHOLD:
            return "red"
        elif yellow_count >= YELLOW_THRESHOLD:
            return "yellow"
        else:
            return "green"
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
    prog_pct = float(data.get("progress_pct", 0.0))
    
    if not respuesta or not correo:
        return jsonify({"error": "Datos incompletos"}), 400
        
    usuario = get_or_create_user(correo)
    
    # --- EXTRACCIÓN Y VINCULACIÓN DEL ID RELACIONAL ---
    pid = None
    try:
        # Intentamos convertir a entero si el frontend envió el ID como string (ej: "15")
        pid = int(practice_name)
    except ValueError:
        # Fallback de compatibilidad: si llega el título de la práctica (ej: de un cliente viejo),
        # buscamos su ID correspondiente en la base de datos
        prac = Practica.query.filter_by(titulo=practice_name).first()
        if prac:
            pid = prac.id

    nueva_respuesta = RespuestaUsuario(
        user_id=usuario.id,
        problema_id=problema_id,
        correo_identificacion=correo,
        respuesta=respuesta,
        practice_name=practice_name,
        practica_id=pid # <--- VINCULACIÓN RELACIONAL OBLIGATORIA
    )
    db.session.add(nueva_respuesta)
    db.session.commit()
    problem_text = get_problem_enunciado(practice_name, problema_id)
    gevent.spawn(auto_grade_answer, nueva_respuesta.id, problem_text, respuesta, prog_pct)
    
    return jsonify({"message": "Respuesta registrada y enviada a evaluación"}), 200

@app.route("/chat/<int:problema_id>", methods=["POST"])
def chat(problema_id: int):
    data = request.get_json() or {}
    user_msg = (data.get("message") or "").strip()
    correo = (data.get("correo_identificacion") or "").strip()
    practice_name = (data.get("practice_name") or "").strip()
    prog_pct = float(data.get("progress_pct", 0.0))
    if not user_msg:
        return jsonify({"status": "error", "message": "Mensaje vacío"}), 400
    usuario = get_or_create_user(correo)
    chat_id = save_chat_turn(usuario, correo, practice_name, problema_id, "user", user_msg)
    gevent.spawn(background_llm_task, app, usuario.id, correo, practice_name, problema_id)
    gevent.spawn(analyze_interaction_semaphore, chat_id, user_msg, correo, prog_pct)
    return jsonify({"status": "processing", "message": "Procesando..."})
    
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
    profesor_id = int(get_jwt_identity())
    
    if request.method == "GET":
        resultados = db.session.query(Usuario).join(ListaClase, Usuario.correo_identificacion == ListaClase.student_email).filter(ListaClase.profesor_id == profesor_id).all()
        data = [{"email": u.correo_identificacion, "nombre": u.nombre or "Estudiante"} for u in resultados]
        return jsonify(data), 200
        
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

@app.route("/api/teacher/send-alert", methods=["POST"])
@jwt_required()
def send_student_alert():
    data = request.get_json()
    student_email = data.get("student_email")
    message = data.get("message")
    
    if not student_email or not message:
        return jsonify({"error": "Faltan datos"}), 400
    
    socketio.emit('teacher_alert', {
        'student_email': student_email,
        'message': message
    })
    
    return jsonify({"msg": "Alerta enviada"}), 200

@app.route("/api/teacher/dashboard-data", methods=["GET"])
@jwt_required()
def dashboard_data():
    profesor_id = int(get_jwt_identity())
    target_student = request.args.get('student_email')
    target_practice = request.args.get('practice_name')

    student_records = ListaClase.query.filter_by(profesor_id=profesor_id).all()
    my_student_emails = [s.student_email for s in student_records]
    
    exercise_records = ListaEjercicios.query.filter_by(profesor_id=profesor_id).all()
    my_practicas_ids = [e.practica_id for e in exercise_records if e.practica_id is not None]

    if not my_student_emails or not my_practicas_ids:
        return jsonify({"respuestas": [], "chats": []}), 200
    
    if target_student:
        if target_student not in my_student_emails:
             return jsonify({"msg": "Acceso denegado a este estudiante"}), 403
        emails_to_query = [target_student]
    else:
        emails_to_query = my_student_emails

    resp_query = RespuestaUsuario.query.filter(
        RespuestaUsuario.correo_identificacion.in_(emails_to_query),
        RespuestaUsuario.practica_id.in_(my_practicas_ids) # <--- AHORA FILTRA POR ID DE PRÁCTICA
    )
    if target_practice:
        try: pid = int(target_practice)
        except: pid = -1
        resp_query = resp_query.filter(RespuestaUsuario.practica_id == pid)
        
    respuestas_db = resp_query.order_by(RespuestaUsuario.created_at.desc()).all()
    
    chat_query = ChatLog.query.filter(
        ChatLog.correo_identificacion.in_(emails_to_query),
        ChatLog.practica_id.in_(my_practicas_ids) # <--- AHORA FILTRA POR ID DE PRÁCTICA
    )
    if target_practice:
        try: pid = int(target_practice)
        except: pid = -1
        chat_query = chat_query.filter(ChatLog.practica_id == pid)
        
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
        "practica": c.practice_name, 
        "role": c.role,
        "content": c.content,
        "fecha": c.created_at.isoformat()
    } for c in chats_db]
    
    return jsonify({"respuestas": respuestas_data, "chats": chat_data}), 200
    
@app.route("/api/teacher/all-users", methods=["GET"])
@jwt_required()
def get_all_registered_users():
    try:
        users = Usuario.query.all()
        data = [{"email": u.correo_identificacion, "nombre": u.nombre or "Estudiante"} for u in users if u.correo_identificacion]
        return jsonify(data), 200
    except Exception as e:
        print(f"Error fetching all users: {e}")
        return jsonify([]), 500

# =========================================
# RUTAS PARA GESTIÓN DE CLASES / GRUPOS
# =========================================

@app.route("/api/teacher/classes", methods=["GET"])
@jwt_required()
def get_teacher_classes():
    prof_id = int(get_jwt_identity())
    grupos = Grupo.query.filter_by(profesor_id=prof_id).order_by(Grupo.created_at.desc()).all()
    
    data = []
    for g in grupos:
        # 1. Obtener estudiantes de esta clase
        rels_est = GrupoEstudiante.query.filter_by(grupo_id=g.id).all()
        emails = [r.student_email for r in rels_est]
        usuarios = Usuario.query.filter(Usuario.correo_identificacion.in_(emails)).all()
        lista_estudiantes = [{"email": u.correo_identificacion, "nombre": u.nombre or "Estudiante"} for u in usuarios]
        
        # 2. Obtener tareas de esta clase
        rels_tar = GrupoTarea.query.filter_by(grupo_id=g.id).all()
        filenames = [r.exercise_filename for r in rels_tar]
        lista_tareas = []
        for fname in filenames:
            meta = get_exercise_metadata(fname)
            lista_tareas.append({"filename": fname, "title": meta["title"]})
            
        # 3. Ensamblar objeto
        data.append({
            "id": g.id,
            "nombre": g.nombre,
            "estudiantes": lista_estudiantes,
            "tareas": lista_tareas
        })
        
    return jsonify(data), 200

@app.route("/api/teacher/classes", methods=["POST"])
@jwt_required()
def create_teacher_class():
    prof_id = int(get_jwt_identity())
    data = request.get_json()
    
    nombre = data.get("nombre")
    estudiantes = data.get("estudiantes", []) # Lista de correos
    tareas = data.get("tareas", []) # Lista de filenames
    
    if not nombre:
        return jsonify({"error": "El nombre de la clase es obligatorio"}), 400
        
    # 1. Crear el grupo base
    nuevo_grupo = Grupo(profesor_id=prof_id, nombre=nombre)
    db.session.add(nuevo_grupo)
    db.session.flush() # Para obtener el ID generado sin hacer commit aún
    
    # 2. Ligar estudiantes
    for email in estudiantes:
        db.session.add(GrupoEstudiante(grupo_id=nuevo_grupo.id, student_email=email))
        
    # 3. Ligar tareas
    for filename in tareas:
        db.session.add(GrupoTarea(grupo_id=nuevo_grupo.id, exercise_filename=filename))
        
    db.session.commit()
    return jsonify({"msg": "Clase creada con éxito", "id": nuevo_grupo.id}), 201

@app.route("/api/teacher/classes/<int:class_id>", methods=["DELETE"])
@jwt_required()
def delete_teacher_class(class_id):
    prof_id = int(get_jwt_identity())
    grupo = Grupo.query.filter_by(id=class_id, profesor_id=prof_id).first()
    if not grupo:
        return jsonify({"error": "Clase no encontrada o acceso denegado"}), 404
    GrupoEstudiante.query.filter_by(grupo_id=class_id).delete()
    GrupoTarea.query.filter_by(grupo_id=class_id).delete()
    db.session.delete(grupo)
    db.session.commit()
    return jsonify({"msg": "Clase eliminada correctamente"}), 200

@app.route("/api/teacher/classes/<int:class_id>", methods=["PUT"])
@jwt_required()
def update_teacher_class(class_id):
    prof_id = int(get_jwt_identity())
    grupo = Grupo.query.filter_by(id=class_id, profesor_id=prof_id).first()
    if not grupo:
        return jsonify({"error": "Clase no encontrada o acceso denegado"}), 404
    data = request.get_json()
    nuevo_nombre = data.get("nombre")
    if nuevo_nombre:
        grupo.nombre = nuevo_nombre
    nuevos_emails = data.get("estudiantes")
    if nuevos_emails is not None:
        GrupoEstudiante.query.filter_by(grupo_id=class_id).delete()
        for email in nuevos_emails:
            db.session.add(GrupoEstudiante(grupo_id=class_id, student_email=email))
    nuevas_tareas = data.get("tareas")
    if nuevas_tareas is not None:
        GrupoTarea.query.filter_by(grupo_id=class_id).delete()
        for fname in nuevas_tareas:
            db.session.add(GrupoTarea(grupo_id=class_id, exercise_filename=fname))
    db.session.commit()
    return jsonify({"msg": "Clase actualizada"}), 200

# --- HELPER PARA FILTRAR EVALUACIONES DEL PROFESOR ---
def get_teacher_filtered_responses(prof_id, status_filter):
    student_records = ListaClase.query.filter_by(profesor_id=prof_id).all()
    my_students = [s.student_email for s in student_records]
    
    exercise_records = ListaEjercicios.query.filter_by(profesor_id=prof_id).all()
    my_practicas_ids = [e.practica_id for e in exercise_records if e.practica_id is not None]
    
    if not my_students or not my_practicas_ids:
        return []
        
    # 3. Consultar cruzando Respuestas con Usuarios y Prácticas para obtener el Título Real
    query = db.session.query(RespuestaUsuario, Usuario.nombre, Practica.titulo).outerjoin(
        Usuario, RespuestaUsuario.correo_identificacion == Usuario.correo_identificacion
    ).outerjoin(
        Practica, RespuestaUsuario.practica_id == Practica.id # <--- NUEVO JOIN
    ).filter(
        RespuestaUsuario.correo_identificacion.in_(my_students),
        RespuestaUsuario.practica_id.in_(my_practicas_ids)
    )
    
    if isinstance(status_filter, list):
        query = query.filter(RespuestaUsuario.status.in_(status_filter))
    else:
        query = query.filter(RespuestaUsuario.status == status_filter)
        
    results = query.order_by(RespuestaUsuario.created_at.desc()).all()
    
    data = []
    for r, nombre, titulo in results:
        data.append({
            "id": r.id,
            "nombre": nombre or "Estudiante",
            "correo": r.correo_identificacion,
            "practica": r.practice_name,
            "titulo_practica": titulo or r.practice_name, # <--- ENVIAMOS EL TÍTULO REAL
            "problema_id": r.problema_id,
            "respuesta": r.respuesta,
            "llm_score": r.llm_score,
            "llm_comment": r.llm_comment,
            "teacher_score": r.teacher_score,
            "teacher_comment": r.teacher_comment,
            "status": r.status,
            "fecha": r.created_at.isoformat() if r.created_at else ""
        })
    return data

@app.route("/api/teacher/grades/pending", methods=["GET"])
@jwt_required()
def get_pending_grades():
    prof_id = int(get_jwt_identity())
    data = get_teacher_filtered_responses(prof_id, "pending")
    return jsonify(data), 200

@app.route("/api/teacher/grades/completed", methods=["GET"])
@jwt_required()
def get_completed_grades():
    prof_id = int(get_jwt_identity())
    data = get_teacher_filtered_responses(prof_id, ["approved", "edited"])
    return jsonify(data), 200

@app.route("/api/teacher/grades/<int:resp_id>", methods=["DELETE"])
@jwt_required()
def delete_grade(resp_id):
    prof_id = int(get_jwt_identity())
    resp = RespuestaUsuario.query.get(resp_id)
    if not resp:
        return jsonify({"msg": "No encontrado"}), 404
    asig = ListaEjercicios.query.filter_by(
        profesor_id=prof_id, practica_id=resp.practica_id
    ).first()
    if not asig:
        return jsonify({"error": "No autorizado para eliminar esta evaluación"}), 403
    db.session.delete(resp)
    db.session.commit()
    return jsonify({"msg": "Evaluación eliminada"}), 200

@app.route("/api/teacher/grades/submit", methods=["POST"])
@jwt_required()
def submit_teacher_grade():
    data = request.get_json()
    resp_id = data.get("id")
    action = data.get("action")
    
    resp = RespuestaUsuario.query.get(resp_id)
    if not resp: return jsonify({"msg": "Not found"}), 404
    
    if action == "approve":
        resp.teacher_score = resp.llm_score
        resp.teacher_comment = data.get("comment") 
        resp.status = "approved"
    elif action == "edit":
        raw_score = data.get("score")
        try:
            score = float(raw_score)
            if not (0 <= score <= 10):
                return jsonify({"error": "La calificación debe estar entre 0 y 10"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Calificación inválida"}), 400
        resp.teacher_score = score
        resp.teacher_comment = data.get("comment")
        resp.status = "edited"
    db.session.commit()
    return jsonify({"msg": "Evaluación actualizada"}), 200
    
@app.route("/api/teacher/status", methods=["GET"])
@jwt_required()
def get_student_statuses():
    subq = db.session.query(
        AnalisisInteraccion.correo_identificacion,
        func.max(AnalisisInteraccion.created_at).label('max_date')
    ).group_by(AnalisisInteraccion.correo_identificacion).subquery()
    
    # Join to get the color associated with that latest timestamp
    latest_entries = db.session.query(AnalisisInteraccion).join(
        subq, 
        (AnalisisInteraccion.correo_identificacion == subq.c.correo_identificacion) & 
        (AnalisisInteraccion.created_at == subq.c.max_date)
    ).all()
    
    status_map = {entry.correo_identificacion: entry.color_asignado for entry in latest_entries}
    return jsonify(status_map), 200

@app.route('/api/student_timeline/<path:email>', methods=['GET'])
@jwt_required()
def get_student_timeline(email):
    """Fetches combined chronological timeline of chat and answers."""
    try:
        chats = db.session.query(AnalisisInteraccion, ChatLog.content).join(
            ChatLog, AnalisisInteraccion.chat_id == ChatLog.id
        ).filter(
            AnalisisInteraccion.correo_identificacion == email
        ).order_by(AnalisisInteraccion.created_at.desc()).limit(25).all()
        
        chat_events = [{
            'type': 'chat',
            'id': c[0].id,
            'timestamp': c[0].created_at.isoformat(),
            'intent': c[0].intent,
            'color': c[0].color_asignado,
            'description': f"Consultó al LLM: {c[0].intent}",
            'content': c[1]
        } for c in chats]

        answers = RespuestaUsuario.query.filter_by(correo_identificacion=email).filter(RespuestaUsuario.status != 'processing').order_by(RespuestaUsuario.created_at.desc()).limit(25).all()
        answer_events = [{
            'type': 'answer',
            'id': a.id,
            'timestamp': a.created_at.isoformat() if a.created_at else hora_ensenada().isoformat(),
            'problem_id': a.problema_id,
            'score': a.llm_score,
            'color': "green" if (a.llm_score or 0) >= 7 else "yellow" if (a.llm_score or 0) >= 4 else "red",
            'description': f"Entregó Respuesta P{a.problema_id} (Calificación: {a.llm_score})",
            'respuesta': a.respuesta
        } for a in answers]

        combined_timeline = sorted(
            chat_events + answer_events, 
            key=lambda x: x['timestamp'], 
            reverse=True
        )

        return jsonify(combined_timeline), 200
    except Exception as e:
        print(f"Error fetching timeline: {e}")
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/teacher/student-profile/<path:student_email>', methods=['GET'])
@jwt_required()
def get_student_profile(student_email):
    profesor_id = int(get_jwt_identity())

    student_records = ListaClase.query.filter_by(profesor_id=profesor_id).all()
    my_student_emails = [s.student_email for s in student_records]
    if student_email not in my_student_emails:
        return jsonify({"error": "Estudiante no autorizado"}), 403

    exercise_records = ListaEjercicios.query.filter_by(profesor_id=profesor_id).all()
    my_practicas_ids = [e.practica_id for e in exercise_records if e.practica_id is not None]

    if not my_practicas_ids:
        return jsonify({}), 200

    respuestas = RespuestaUsuario.query.filter(
        RespuestaUsuario.correo_identificacion == student_email,
        RespuestaUsuario.practica_id.in_(my_practicas_ids) # <--- AHORA FILTRA POR ID DE PRÁCTICA
    ).order_by(RespuestaUsuario.problema_id.asc()).all()

    chats = ChatLog.query.filter(
        ChatLog.correo_identificacion == student_email,
        ChatLog.practica_id.in_(my_practicas_ids) # <--- AHORA FILTRA POR ID DE PRÁCTICA
    ).order_by(ChatLog.created_at.asc()).all()

    profile_data = {}
    practica_titles = {
        p.id: p.titulo
        for p in Practica.query.filter(Practica.id.in_(my_practicas_ids)).all()
    }
    
    for r in respuestas:
        # Intenta traducir el ID a su Título Real, si falla usa el original
        p_name = practica_titles.get(r.practica_id, r.practice_name)
        if p_name not in profile_data:
            profile_data[p_name] = {"problemas": {}}
        
        prob_id = str(r.problema_id)
        if prob_id not in profile_data[p_name]["problemas"]:
            profile_data[p_name]["problemas"][prob_id] = {"respuesta": None, "chats": []}
            
        profile_data[p_name]["problemas"][prob_id]["respuesta"] = {
            "texto": r.respuesta,
            "llm_score": r.llm_score,
            "llm_comment": r.llm_comment,
            "teacher_score": r.teacher_score,
            "teacher_comment": r.teacher_comment,
            "status": r.status,
            "fecha": r.created_at.isoformat()
        }

    for c in chats:
        p_name = practica_titles.get(c.practica_id, c.practice_name)
        prob_id = str(c.problema_id)
        if p_name not in profile_data:
            profile_data[p_name] = {"problemas": {}}
        if prob_id not in profile_data[p_name]["problemas"]:
            profile_data[p_name]["problemas"][prob_id] = {"respuesta": None, "chats": []}
        
        profile_data[p_name]["problemas"][prob_id]["chats"].append({
            "role": c.role,
            "content": c.content,
            "fecha": c.created_at.isoformat()
        })
    
    reportes = ReporteDesempeno.query.filter_by(student_email=student_email).all()
    for r in reportes:
        if r.practice_name in profile_data:
            profile_data[r.practice_name]["reporte"] = {
                "perfil_estudiante": r.perfil_estudiante,
                "persistencia": r.persistencia,
                "diagnostico_general": r.diagnostico_general,
                "fecha": r.created_at.isoformat()
            }
            
    return jsonify(profile_data), 200

@app.route('/api/teacher/generate-report', methods=['POST'])
@jwt_required()
def generate_student_report():
    data = request.get_json()
    email = data.get('student_email')
    practice_title = data.get('practice_name') # El frontend envía el Título
    prac_obj = Practica.query.filter_by(titulo=practice_title).first()
    if prac_obj:
        chats = ChatLog.query.filter_by(correo_identificacion=email, practica_id=prac_obj.id).order_by(ChatLog.id.asc()).all()
        respuestas = RespuestaUsuario.query.filter_by(correo_identificacion=email, practica_id=prac_obj.id).order_by(RespuestaUsuario.problema_id.asc()).all()
    else:
        chats = ChatLog.query.filter_by(correo_identificacion=email, practice_name=practice_title).order_by(ChatLog.id.asc()).all()
        respuestas = RespuestaUsuario.query.filter_by(correo_identificacion=email, practice_name=practice_title).order_by(RespuestaUsuario.problema_id.asc()).all()
    interacciones = AnalisisInteraccion.query.filter_by(correo_identificacion=email).all()
    
    if not chats and not respuestas:
        return jsonify({"error": "No hay datos suficientes para analizar."}), 400

    transcript_lines = []
    for c in chats:
        role = "ESTUDIANTE" if c.role == "user" else ("PROFESOR" if c.role == "teacher" else "TUTOR IA")
        transcript_lines.append(f"[{role} - P{c.problema_id}]: {c.content}")
        
    conteo_alertas = {"green": 0, "yellow": 0, "red": 0}
    for i in interacciones:
        if i.color_asignado in conteo_alertas:
            conteo_alertas[i.color_asignado] += 1
    
    transcript_lines.append("\n--- RESUMEN DE SEMÁFORO COGNITIVO ---")
    transcript_lines.append(f"Interacciones Seguras (Verdes): {conteo_alertas['green']}")
    transcript_lines.append(f"Alertas de Confusión (Amarillas): {conteo_alertas['yellow']}")
    transcript_lines.append(f"Alertas Críticas (Rojas): {conteo_alertas['red']}")
    
    transcript_lines.append("\n--- RESPUESTAS FINALES ENTREGADAS ---")
    for r in respuestas:
        nota = r.teacher_score if r.teacher_score is not None else (r.llm_score or 0)
        transcript_lines.append(f"[P{r.problema_id} - Nota: {nota}/10]: {r.respuesta}")

    transcript = "\n".join(transcript_lines)

    # 3. Prompt Basado en tu Jupyter Notebook
    global_json = """{
      "perfil_estudiante": "Autorregulado",
      "persistencia": "Alta (productiva)",
      "diagnostico_general": "Fortalezas... Debilidades..."
    }"""
    
    prompt = f"""
    Actúa como un investigador educativo que analiza interacciones entre estudiantes y un Tutor Inteligente potenciado por LLMs.
    Busca patrones generales de aprendizaje en la conversación del estudiante durante la práctica '{practice_title}'.
    Identifica:
    1. **perfil_estudiante**: Elige UNO: "Autorregulado", "Dependiente de pistas", o "Abuso del sistema (gaming)".
    2. **persistencia**: Elige UNA: "Alta (productiva)", "Media (mixta)", "Baja (rendición temprana)", o "Improductiva (insistente en error)".
    3. **diagnostico_general**: Un resumen cualitativo técnico corto sobre sus fortalezas y debilidades cognitivas...
    
    Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura:
    {global_json}

    Estudiante: {email}
    --- INICIO DE TRANSCRIPCIÓN ---
    {transcript}
    --- FIN DE TRANSCRIPCIÓN ---
    """

    try:
        response_text = call_mistral([
            {"role": "system", "content": "Eres un investigador educativo experto. Responde sólo en JSON."},
            {"role": "user", "content": prompt}
        ], temperature=0.2, max_tokens=1000)
        try:
            parsed = json.loads(response_text)
        except:
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}
        practica_id_para_buscar = prac_obj.id if prac_obj else None
        if practica_id_para_buscar:
            reporte = ReporteDesempeno.query.filter_by(
                student_email=email, practica_id=practica_id_para_buscar
            ).first()
        else:
            reporte = ReporteDesempeno.query.filter_by(
                student_email=email, practice_name=practice_title
            ).first()
        if not reporte:
            reporte = ReporteDesempeno(
                student_email=email,
                practice_name=practice_title,
                practica_id=practica_id_para_buscar
            )
            db.session.add(reporte)
        reporte.perfil_estudiante = parsed.get("perfil_estudiante", "No determinado")
        reporte.persistencia = parsed.get("persistencia", "No determinada")
        reporte.diagnostico_general = parsed.get("diagnostico_general", "Error al procesar el diagnóstico.")
        reporte.created_at = hora_ensenada()
        db.session.commit()
        return jsonify({"msg": "Reporte generado"}), 200
    except Exception as e:
        print(f"Error generando reporte: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/public/teachers", methods=["GET"])
def get_public_teachers():
    """Returns a list of all teachers for the student registration dropdown."""
    teachers = Profesor.query.all()
    data = [{"id": t.id, "nombre": t.nombre, "email": t.email} for t in teachers]
    return jsonify(data), 200

@app.route("/api/student/register", methods=["POST"])
def student_register():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    nombre = data.get("nombre")
    teacher_ids = data.get("teacher_ids", [])

    if not email or not password or not nombre or not teacher_ids:
        return jsonify({"msg": "Faltan datos obligatorios o no seleccionó profesores"}), 400

    if Usuario.query.filter_by(correo_identificacion=email).first():
        return jsonify({"msg": "El correo ya está registrado"}), 400

    hashed = generate_password_hash(password)
    nuevo_estudiante = Usuario(correo_identificacion=email, password_hash=hashed, nombre=nombre)
    db.session.add(nuevo_estudiante)
    db.session.commit()

    for t_id in teacher_ids:
        exists = ListaClase.query.filter_by(profesor_id=t_id, student_email=email).first()
        if not exists:
            db.session.add(ListaClase(profesor_id=t_id, student_email=email))
    
    db.session.commit()
    return jsonify({"msg": "Estudiante registrado y adscrito a profesores exitosamente"}), 201
    
@app.route("/api/student/login", methods=["POST"])
def student_login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    
    user = Usuario.query.filter_by(correo_identificacion=email).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"msg": "Credenciales inválidas"}), 401
        
    additional_claims = {"role": "student", "email": user.correo_identificacion}
    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    
    return jsonify(access_token=access_token, nombre=user.nombre, correo=user.correo_identificacion), 200

@app.route("/api/student/my-teachers", methods=["GET"])
@jwt_required()
def get_student_teachers():
    """Returns the list of teachers this student is officially registered to."""
    claims = get_jwt()
    if claims.get("role") != "student":
        return jsonify({"msg": "Acceso denegado. Rol incorrecto."}), 403
    
    student_email = claims.get("email")
    clases = ListaClase.query.filter_by(student_email=student_email).all()
    mis_profesores_ids = [c.profesor_id for c in clases]
    
    if not mis_profesores_ids:
        return jsonify([]), 200
        
    profesores = Profesor.query.filter(Profesor.id.in_(mis_profesores_ids)).all()
    data = [{"nombre": p.nombre, "email": p.email} for p in profesores]
    return jsonify(data), 200

@app.route("/api/student/my-active-exercises", methods=["GET"])
@jwt_required()
def get_student_active_exercises():
    claims = get_jwt()
    if claims.get("role") != "student":
        return jsonify({"msg": "Acceso denegado. Rol incorrecto."}), 403
    
    student_email = claims.get("email")
    
    clases = ListaClase.query.filter_by(student_email=student_email).all()
    mis_profesores_ids = [c.profesor_id for c in clases]
    
    if not mis_profesores_ids:
        return jsonify([]), 200

    ejercicios_activos = ListaEjercicios.query.filter(
        ListaEjercicios.profesor_id.in_(mis_profesores_ids),
        ListaEjercicios.is_active == True
    ).all()
    
    unique_ids = {e.practica_id for e in ejercicios_activos if e.practica_id}
    
    data = [get_exercise_metadata(str(pid)) for pid in unique_ids]
    return jsonify(data), 200
  
# --- REPORTE DE SESIÓN EN VIVO ---

@app.route("/api/teacher/live-session/generate", methods=["POST"])
@jwt_required()
def generate_live_session_report():
    profesor_id = int(get_jwt_identity())
    data = request.get_json()
    
    # 1. Validación de fechas
    try:
        start_time = dt.datetime.fromisoformat(data.get("start_time"))
        end_time = dt.datetime.fromisoformat(data.get("end_time"))
    except Exception as e:
        return jsonify({"error": "Fechas inválidas"}), 400

    # 2. Obtener lista de mis estudiantes asignados
    mis_estudiantes = [s.student_email for s in ListaClase.query.filter_by(profesor_id=profesor_id).all()]
    if not mis_estudiantes:
        return jsonify({"error": "No tienes alumnos asignados."}), 400

    # 3. Recopilación de TODOS los datos relevantes en el rango de tiempo
    # Semáforo
    interacciones = AnalisisInteraccion.query.filter(
        AnalisisInteraccion.correo_identificacion.in_(mis_estudiantes),
        AnalisisInteraccion.created_at >= start_time,
        AnalisisInteraccion.created_at <= end_time
    ).all()
    
    # Respuestas (Solo las dadas durante la sesión)
    respuestas = RespuestaUsuario.query.filter(
        RespuestaUsuario.correo_identificacion.in_(mis_estudiantes),
        RespuestaUsuario.created_at >= start_time,
        RespuestaUsuario.created_at <= end_time
    ).all()
    
    # Chats (Solo durante la sesión)
    chats = ChatLog.query.filter(
        ChatLog.correo_identificacion.in_(mis_estudiantes),
        ChatLog.created_at >= start_time,
        ChatLog.created_at <= end_time
    ).all()

    if not interacciones and not respuestas and not chats:
        return jsonify({"error": "No hubo actividad de estudiantes durante esta sesión."}), 400

    # 4. Estructurar la Data por Estudiante
    # Recopilamos qué prácticas se usaron para extraer enunciados
    practicas_involucradas = set()
    for item in respuestas + chats:
        if item.practice_name: practicas_involucradas.add(item.practice_name)
    
    # Pre-cargar descripciones de prácticas y problemas
    enunciados_cache = {}
    for prac in practicas_involucradas:
        meta = get_exercise_metadata(prac)
        enunciados_cache[prac] = meta

    estudiantes_data = {}
    
    # Inicializar a los estudiantes que tuvieron CUALQUIER tipo de actividad
    active_emails = set(i.correo_identificacion for i in interacciones + respuestas + chats)
    
    for email in active_emails:
        estudiantes_data[email] = {
            "semaforo": {"green": 0, "yellow": 0, "red": 0},
            "transcripcion_chats": [],
            "respuestas_finales": []
        }

    # Llenar Semáforo
    for i in interacciones:
        estudiantes_data[i.correo_identificacion]["semaforo"][i.color_asignado] += 1
        
    # Llenar Chats
    for c in chats:
        role = "Estudiante" if c.role == "user" else ("Profesor" if c.role == "teacher" else "IA")
        practica_desc = enunciados_cache.get(c.practice_name, {}).get("description", "Sin desc.")
        # Buscamos el enunciado exacto
        enunciado = "No encontrado"
        for p in enunciados_cache.get(c.practice_name, {}).get("problemas", []):
            if p.get("id") == c.problema_id:
                enunciado = p.get("enunciado", "No encontrado")
                break
                
        estudiantes_data[c.correo_identificacion]["transcripcion_chats"].append(
            f"[Contexto: {c.practice_name} - {practica_desc} | Ejercicio: {enunciado}]\n{role}: {c.content}"
        )

    # Llenar Respuestas
    for r in respuestas:
        estudiantes_data[r.correo_identificacion]["respuestas_finales"].append(
            f"[Práctica: {r.practice_name} | Problema: {r.problema_id} | Entregó]: {r.respuesta}"
        )

    # 5. Generar Prompts Masivos (Por Estudiante y Uno General)
    final_report = []
    results_map = {}

    def analizar_estudiante(email, data):
        transcripcion_corta = "\n".join(data["transcripcion_chats"][-15:])
        respuestas_texto = "\n".join(data["respuestas_finales"])
        prompt_estudiante = f"""
        Actúa como un profesor experto evaluando el desempeño del estudiante '{email}'.
        Métricas de Semáforo: Verdes: {data['semaforo']['green']}, Amarillas: {data['semaforo']['yellow']}, Rojas: {data['semaforo']['red']}
        Respuestas Entregadas:\n{respuestas_texto}
        Transcripción de Chat:\n{transcripcion_corta}
        Genera un análisis cualitativo en español con: 1. Puntos fuertes. 2. Debilidades. 3. Si requiere intervención.
        Devuelve solo párrafos, sin markdown, sin saludo.
        """
        try:
            analisis = call_mistral([
                {"role": "system", "content": "Eres un analista académico estricto."},
                {"role": "user", "content": prompt_estudiante}
            ], temperature=0.3, max_tokens=300)
        except Exception as e:
            print(f"Error evaluando a {email}: {e}")
            analisis = "Error al conectar con IA para este estudiante."
        results_map[email] = analisis

    # Lanzar todos en paralelo con gevent
    greenlets = [gevent.spawn(analizar_estudiante, email, data) for email, data in estudiantes_data.items()]
    gevent.joinall(greenlets, timeout=90)  # Espera máximo 90s al total

    final_report = []
    for email, data in estudiantes_data.items():
        final_report.append({
            "Estudiante": email,
            "Interacciones (Verde)": data["semaforo"]["green"],
            "Alertas (Amarillo)": data["semaforo"]["yellow"],
            "Riesgo (Rojo)": data["semaforo"]["red"],
            "Análisis Cualitativo IA": results_map.get(email, "Sin análisis generado.")
        })

    # 6. Generar el Párrafo General del Grupo
    if final_report:
        prompt_grupo = f"""
        Actúa como un director de escuela. Acabas de recibir las evaluaciones individuales de los estudiantes que participaron en la sesión de laboratorio.
        Aquí tienes los resúmenes de cada uno:
        
        {json.dumps([{"Estudiante": r["Estudiante"], "Analisis": r["Análisis Cualitativo IA"]} for r in final_report])}
        
        Redacta UN SOLO PÁRRAFO GENERALIZADO resumiendo cómo fue el rendimiento global del grupo, cuáles fueron los problemas más comunes compartidos y cuál debe ser el enfoque de la siguiente clase grupal.
        No uses markdown, no saludes, escribe como un reporte formal.
        """
        try:
            analisis_grupal = call_mistral([
                {"role": "system", "content": "Eres un director de academia."},
                {"role": "user", "content": prompt_grupo}
            ], temperature=0.4, max_tokens=400)
        except Exception as e:
            analisis_grupal = "No se pudo generar el análisis grupal."
            
        # Lo agregamos como una "fila" especial al final del reporte
        final_report.append({
            "Estudiante": ">>> RESUMEN GLOBAL DEL GRUPO <<<",
            "Interacciones (Verde)": "-",
            "Alertas (Amarillo)": "-",
            "Riesgo (Rojo)": "-",
            "Análisis Cualitativo IA": analisis_grupal
        })

    # 7. Guardar en BD
    nuevo_reporte = ReporteSesionVivo(
        profesor_id=profesor_id,
        start_time=start_time,
        end_time=end_time,
        report_data=final_report
    )
    db.session.add(nuevo_reporte)
    db.session.commit()

    return jsonify({"msg": "Reporte generado", "report_id": nuevo_reporte.id}), 200

@app.route("/api/teacher/live-session/download", methods=["GET"])
def download_live_session_report():
    token = request.args.get("token")
    report_id = request.args.get("report_id")
    
    try:
        decoded = decode_token(token)
        profesor_id = int(decoded["sub"])
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    reporte = ReporteSesionVivo.query.filter_by(id=report_id, profesor_id=profesor_id).first()
    if not reporte:
        return jsonify({"error": "Reporte no encontrado"}), 404

    df = pd.DataFrame(reporte.report_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Análisis de Sesión")
    
    output.seek(0)
    file_name = f"Reporte_Sesion_{reporte.start_time.strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(output, download_name=file_name, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- REPORTE CUANTITATIVO DE EVALUACIONES ---

@app.route("/api/teacher/grades/download", methods=["GET"])
def download_grades_report():
    token = request.args.get("token")
    try:
        decoded = decode_token(token)
        prof_id = int(decoded["sub"])
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    practice_filter = request.args.get("practice")
    student_filter = request.args.get("student")

    # Reutilizamos tu helper existente para asegurar seguridad
    respuestas_crudas = get_teacher_filtered_responses(prof_id, ["approved", "edited", "pending"])
    
    if not respuestas_crudas:
        return jsonify({"error": "No hay datos para exportar"}), 404

    # Construir data plana
    data_plana = []
    for r in respuestas_crudas:
        if practice_filter and practice_filter != "Todas las tareas" and r["practica"] != practice_filter:
            continue
        if student_filter and student_filter != "Todos los estudiantes" and r["correo"] != student_filter:
            continue
            
        final_score = r["teacher_score"] if r["teacher_score"] is not None else (r["llm_score"] or 0)
        
        data_plana.append({
            "Nombre": r["nombre"],
            "Correo": r["correo"],
            "Práctica": r.get("titulo_practica", r["practica"]), # <--- USA LA LLAVE CREADA EN EL PASO 2
            "Problema": f"Ejercicio {r['problema_id']}",
            "Calificación": float(final_score)
        })

    if not data_plana:
        return jsonify({"error": "Los filtros seleccionados no arrojaron resultados"}), 404

    df = pd.DataFrame(data_plana)
    
    # Pivot Table: Alumnos como filas, Ejercicios como columnas
    pivot_df = df.pivot_table(
        index=["Nombre", "Correo", "Práctica"], 
        columns="Problema", 
        values="Calificación", 
        aggfunc="first"
    ).reset_index()
    
    # Rellenar vacíos con 0 y sumar el total
    numeric_cols = [c for c in pivot_df.columns if "Ejercicio" in str(c)]
    pivot_df[numeric_cols] = pivot_df[numeric_cols].fillna(0)
    pivot_df["Suma Total"] = pivot_df[numeric_cols].sum(axis=1)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pivot_df.to_excel(writer, index=False, sheet_name="Calificaciones")
    
    output.seek(0)
    return send_file(output, download_name="Reporte_Calificaciones.xlsx", as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def process_pdf_background(app_obj, file_bytes, filename, prof_id):
    """Esta función corre en segundo plano sin que el servidor la mate por tiempo"""
    with app_obj.app_context():
        try:
            stream = BytesIO(file_bytes)
            text = ""
            print("📖 [Upload] Leyendo con pdfplumber...")
            with pdfplumber.open(stream) as pdf:
                for i, page in enumerate(pdf.pages):
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"

            if len(text.strip()) < 50:
                print("⚠️ [Upload] PDF sin texto. Activando OCR fallback...")
                images = convert_from_bytes(stream.getvalue())
                for img in images:
                    text += pytesseract.image_to_string(img, lang="spa") + "\n"

            if len(text.strip()) < 50:
                print("❌ [Upload] PDF ilegible.")
                return

            print("🤖 [Upload] Enviando a Mistral...")
            sys_prompt = "Eres un asistente experto en pedagogía. Extrae los ejercicios del documento provisto y devuelve EXCLUSIVAMENTE un JSON válido con esta estructura: {\"titulo\": \"...\", \"descripcion\": \"...\", \"max_time\": 60, \"problemas\": [{\"id\": 1, \"enunciado\": \"...\"}]}"

            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"DOCUMENTO:\n{text[:15000]}"}
            ]

            raw_json = call_mistral(messages, temperature=0.1, max_tokens=2500)

            import re
            match = re.search(r'\{.*\}', raw_json, re.DOTALL)
            if not match:
                print(f"❌ [Upload] IA no devolvió JSON válido.")
                return

            data_ia = json.loads(match.group(0))

            nueva_practica = Practica(
                titulo=data_ia.get("titulo", filename.replace(".pdf", "")),
                descripcion=data_ia.get("descripcion", ""),
                max_time=int(data_ia.get("max_time", 60)),
                profesor_id=prof_id,
                rubricas=[]
            )
            db.session.add(nueva_practica)
            db.session.flush()

            for prob in data_ia.get("problemas", []):
                nuevo_prob = Problema(
                    practica_id=nueva_practica.id,
                    numero_ejercicio=int(prob.get("id", prob.get("numero", 1))),
                    enunciado=str(prob.get("enunciado", ""))
                )
                db.session.add(nuevo_prob)

            db.session.add(ListaEjercicios(
                profesor_id=prof_id,
                exercise_filename=f"MIGRADO_{nueva_practica.id}",
                practica_id=nueva_practica.id,
                is_active=True
            ))

            db.session.commit()
            print("✅ [Upload] Tarea guardada con éxito.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ [Upload] Error interno: {str(e)}")

@app.route("/api/teacher/exercises/upload", methods=["POST"])
@jwt_required()
def upload_exercise_pdf():
    prof_id = int(get_jwt_identity())
    filename = request.args.get("filename", "documento.pdf")
    if request.files:
        file = list(request.files.values())[0]
        filename = file.filename or filename
        file_bytes = file.read()
    elif request.data:
        file_bytes = request.data
    else:
        return jsonify({"error": "No se recibió el archivo"}), 400
    if not filename.lower().endswith('.pdf'):
        return jsonify({"error": "Solo se permiten PDFs"}), 400
    gevent.spawn(process_pdf_background, app, file_bytes, filename, prof_id)
    return jsonify({"msg": "Recibido. Procesando en segundo plano"}), 202

# =========================================
# RUTAS DE TAREAS / EJERCICIOS (NUEVA ARQUITECTURA RELACIONAL)
# =========================================

@app.route("/api/exercises/available", methods=["GET"])
@jwt_required()
def get_available_exercises():
    prof_id = int(get_jwt_identity())
    practicas = Practica.query.filter((Practica.profesor_id == None) | (Practica.profesor_id != prof_id)).order_by(Practica.id.desc()).all()
    data = []
    for p in practicas:
        probs = Problema.query.filter_by(practica_id=p.id).order_by(Problema.numero_ejercicio).all()
        data.append({
            "filename": str(p.id),
            "practica_id": p.id,
            "title": p.titulo,
            "description": p.descripcion,
            "max_time": p.max_time * 60,
            "num_problems": len(probs),
            "problemas": [{"id": pr.numero_ejercicio, "enunciado": pr.enunciado} for pr in probs]
        })
    return jsonify(data), 200

@app.route("/api/teacher/my-exercises", methods=["GET"])
@jwt_required()
def get_my_exercises():
    prof_id = int(get_jwt_identity())
    asignaciones = ListaEjercicios.query.filter_by(profesor_id=prof_id).all()
    data = []
    for asig in asignaciones:
        p = Practica.query.get(asig.practica_id)
        if p:
            probs = Problema.query.filter_by(practica_id=p.id).order_by(Problema.numero_ejercicio).all()
            data.append({
                "filename": str(p.id),
                "practica_id": p.id,
                "title": p.titulo,
                "description": p.descripcion,
                "max_time": p.max_time * 60,
                "num_problems": len(probs),
                "problemas": [{"id": pr.numero_ejercicio, "enunciado": pr.enunciado} for pr in probs], # <--- AGREGADO
                "is_active": asig.is_active,
                "is_mine": p.profesor_id == prof_id or p.profesor_id is None
            })
    return jsonify(data), 200

@app.route("/api/teacher/my-exercises", methods=["POST"])
@jwt_required()
def add_my_exercise():
    prof_id = int(get_jwt_identity())
    data = request.get_json()
    # El front actual manda "filename", extraemos el ID de ahí
    pid = data.get("practica_id") or data.get("filename") 
    if not pid: return jsonify({"error": "ID de práctica faltante"}), 400
    
    pid = int(pid)
    existe = ListaEjercicios.query.filter_by(profesor_id=prof_id, practica_id=pid).first()
    if not existe:
        db.session.add(ListaEjercicios(profesor_id=prof_id, practica_id=pid, exercise_filename=f"MIGRADO_{pid}", is_active=True))
        db.session.commit()
    return jsonify({"msg": "Tarea agregada a tu lista"}), 200

@app.route("/api/teacher/my-exercises", methods=["DELETE"])
@jwt_required()
def remove_my_exercise():
    prof_id = int(get_jwt_identity())
    data = request.get_json()
    pid = data.get("practica_id") or data.get("filename")
    if pid:
        ListaEjercicios.query.filter_by(profesor_id=prof_id, practica_id=int(pid)).delete()
        db.session.commit()
    return jsonify({"msg": "Tarea removida de tu lista"}), 200

@app.route("/api/teacher/my-exercises/toggle", methods=["PUT"])
@jwt_required()
def toggle_my_exercise():
    prof_id = int(get_jwt_identity())
    data = request.get_json() or {}
    
    # Extraer el ID o nombre de forma segura
    pid = data.get("practica_id") or data.get("filename")
    if not pid:
        return jsonify({"error": "Identificador faltante"}), 400
        
    try:
        # 1. Intentar buscar por ID relacional (Nuevo estándar)
        pid_int = int(pid)
        asig = ListaEjercicios.query.filter_by(profesor_id=prof_id, practica_id=pid_int).first()
    except ValueError:
        # 2. Fallback: buscar por texto si es un archivo histórico sin migrar
        asig = ListaEjercicios.query.filter_by(profesor_id=prof_id, exercise_filename=str(pid)).first()
        
    # 3. Si no lo encuentra por ID, intentar buscar por nombre de archivo por seguridad
    if not asig:
        asig = ListaEjercicios.query.filter_by(profesor_id=prof_id, exercise_filename=str(pid)).first()
        
    if asig:
        asig.is_active = not asig.is_active
        db.session.commit()
        return jsonify({"is_active": asig.is_active, "msg": "Estado actualizado"}), 200
        
    return jsonify({"error": "Asignación no encontrada"}), 404

@app.route("/api/exercises/detail/<identificador>", methods=["GET"])
@jwt_required()
def get_exercise_detail(identificador):
    # Soporta tanto el nuevo ID numérico como el viejo formato .json si algún alumno lo pide
    try:
        pid = int(identificador)
        p = Practica.query.get(pid)
    except ValueError:
        p = Practica.query.filter_by(titulo=identificador).first() # Fallback

    if not p: return jsonify({"error": "Práctica no encontrada"}), 404
    
    probs = Problema.query.filter_by(practica_id=p.id).order_by(Problema.numero_ejercicio).all()
    prob_list = [{"id": pr.numero_ejercicio, "enunciado": pr.enunciado} for pr in probs]
    
    return jsonify({
        "id": p.id,
        "filename": str(p.id),
        "title": p.titulo,
        "description": p.descripcion,
        "max_time": p.max_time * 60,
        "rubricas": p.rubricas or [],
        "problemas": prob_list
    }), 200

# NUEVO ENDPOINT PARA FASE 4: Editar Tareas
@app.route("/api/teacher/exercises/<int:practica_id>", methods=["PUT"])
@jwt_required()
def edit_exercise(practica_id):
    prof_id = int(get_jwt_identity())
    p = Practica.query.get(practica_id)
    if not p: return jsonify({"error": "Práctica no encontrada"}), 404
    
    # Bloqueo de seguridad: Solo el creador original puede modificarla
    if p.profesor_id != prof_id and p.profesor_id is not None:
        return jsonify({"error": "No tienes permiso para editar esta tarea."}), 403
        
    data = request.get_json()
    p.titulo = data.get("title", p.titulo)
    p.descripcion = data.get("description", p.descripcion)
    
    max_t = data.get("max_time")
    if max_t is not None:
        p.max_time = int(max_t) # El frontend enviará minutos directamente
        
    p.rubricas = data.get("rubricas", p.rubricas)
    
    # Actualizar problemas (borrado y recreación limpia)
    Problema.query.filter_by(practica_id=p.id).delete()
    for prob in data.get("problemas", []):
        nuevo_prob = Problema(
            practica_id=p.id,
            numero_ejercicio=int(prob.get("id", 1)),
            enunciado=prob.get("enunciado", "")
        )
        db.session.add(nuevo_prob)
        
    db.session.commit()
    return jsonify({"msg": "Tarea actualizada correctamente"}), 200
# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------

if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False, allow_unsafe_werkzeug=True)
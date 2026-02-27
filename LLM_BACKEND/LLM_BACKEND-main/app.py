import gevent.monkey
import os, random, string, requests, json, threading
import datetime as dt
import warnings
from typing import List, Dict
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from sqlalchemy import text, inspect
from flask_cors import CORS
from pinecone import Pinecone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

warnings.filterwarnings("ignore", category=DeprecationWarning)
gevent.monkey.patch_all()

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
RED_FLAG_INTENTS = ["demand for direct answer", "negative expression"]
YELLOW_FLAG_INTENTS = ["off-topic", "expression of incomprehension"]
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
socketio = SocketIO(app, cors_allowed_origins="*")

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
    respuesta = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    # Extra LLM-based variables
    llm_score = db.Column(db.Float, nullable=True)       # 0.0 to 10.0
    llm_comment = db.Column(db.Text, nullable=True)      # Feedback generated by LLM
    teacher_score = db.Column(db.Float, nullable=True)   # Final score assigned by teacher
    teacher_comment = db.Column(db.Text, nullable=True)  # Final comment by teacher
    status = db.Column(db.String(20), default="pending") # "pending", "approved", "edited"

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

class AnalisisInteraccion(db.Model):
    __tablename__ = "railway_analisis_interaccion"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("railway_chat_log.id"), nullable=False)
    correo_identificacion = db.Column(db.String(128), nullable=True)
    intent = db.Column(db.String(50), nullable=True)     # e.g., "Call for Assistance"
    dimension = db.Column(db.String(50), nullable=True)   # "Productive" or "Unproductive"
    color_asignado = db.Column(db.String(50), default="green") # green, yellow, red
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

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
    return log.id
    
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
            ).order_by(ChatLog.id.desc()).first()
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

def get_exercise_metadata(filename):
    try:
        path = os.path.join(EXERCISES_PATH, filename)
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {
                "filename": filename,
                "title": data.get("title", filename),
                "description": data.get("description", "Sin descripción disponible."),
                "max_time": data.get("max_time", 0),
                "num_problems": len(data.get("problemas", []))
            }
    except Exception as e:
        print(f"Error leyendo metadata de {filename}: {e}")
        return {
            "filename": filename, 
            "title": filename, 
            "description": "Error al leer archivo.", 
            "max_time": 0, 
            "num_problems": 0
        }

# 1. Semaphore Analysis Function (Fixed Context)
def analyze_interaction_semaphore(chat_log_id, user_message, correo):
    """
    Classifies intent and assigns a color based on the Article's heuristics.
    """
    # We must wrap the ENTIRE execution in the app context to query DB
    with app.app_context():
        # Prompt derived from your Article/Colab logic
        sys_prompt = (
            "Eres un experto en Learning Analytics. Clasifica la interacción del estudiante.\n"
            "CATEGORÍAS:\n"
            "1. Call for Assistance (Productive)\n"
            "2. Conceptual Query (Productive)\n"
            "3. Confirmation of Reasoning (Productive)\n"
            "4. Request for Example (Productive)\n"
            "5. Calculation or Operation (Productive)\n"
            "6. Demand for Direct Answer (Unproductive - RED FLAG)\n"
            "7. Expression of Incomprehension (Unproductive - YELLOW FLAG)\n"
            "8. Off-Topic (Unproductive - YELLOW FLAG)\n"
            "9. Negative Expression (Unproductive - RED FLAG)\n"
            "10. Other (Neutral)\n\n"
            "Devuelve SOLO un JSON: {\"intent\": \"...\", \"dimension\": \"Productive/Unproductive\"}"
        )
        
        try:
            # LLM Call
            response_text = call_mistral([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_message}
            ], temperature=0.2, max_tokens=100)
            
            # Parse JSON
            import json, re
            try:
                data = json.loads(response_text)
            except:
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                data = json.loads(match.group(0)) if match else {"intent": "Other", "dimension": "Neutral"}

            intent = data.get("intent", "Other")
            
            # --- TRAFFIC LIGHT HEURISTICS ---
            color = "green" # Default
            
            # RED: Direct Answer or Aggression
            if intent in ["Demand for Direct Answer", "Negative Expression"]:
                color = "red"
                
            # YELLOW: Confusion or Off-Topic (>2 recent occurrences)
            elif intent in ["Expression of Incomprehension", "Off-Topic"]:
                since = dt.datetime.utcnow() - dt.timedelta(minutes=5)
                # Now this query works because we are inside app.app_context()
                recent_issues = AnalisisInteraccion.query.filter(
                    AnalisisInteraccion.correo_identificacion == correo,
                    AnalisisInteraccion.intent.in_(["Expression of Incomprehension", "Off-Topic"]),
                    AnalisisInteraccion.created_at >= since
                ).count()
                
                if recent_issues >= 2: 
                    color = "yellow"
            
            intent_raw = data.get("intent", "Other")
            dimension_safe = str(data.get("dimension", "Neutral"))[:50]
            
            # Save to DB
            analysis = AnalisisInteraccion(
                chat_id=chat_log_id,
                correo_identificacion=correo,
                intent=intent_raw,
                dimension=dimension_safe,
                color_asignado="green" 
            )
            db.session.add(analysis)
            db.session.commit()           
            calculated_color = calculate_sliding_window_color(correo)
            
            # Update the record with the calculated color
            analysis.color_asignado = calculated_color
            db.session.commit()

            print(f"🚦 Semaphore ({SEMAPHORE_WINDOW_MINUTES}m window): {correo} -> {intent_raw} | State: {calculated_color}")
            
            # Emit the CALCULATED color based on history
            socketio.emit('student_activity', {
                'type': 'chat',
                'student_email': correo,
                'status': calculated_color,
                'intent': intent_raw,
                'last_message': user_message,
                'progress_pct': prog_pct,
                'timestamp': dt.datetime.utcnow().isoformat(),
                'analysis_id': analysis.id
            })
            
        except Exception as e:
            print(f"❌ Error in Semaphore Analysis: {e}")
            
# 2. Automated Grading Function
def auto_grade_answer(respuesta_id, problem_text, student_answer):
    example_json = """{
        "calificación": 10,
        "comentario": "Solución correcta, cuenta con el procedimiento completo y una explicación exhaustiva."
    }"""
    user_prompt = f"""
        Actúa como un profesor experto de ciencias computacionales que evalúa una práctica universitaria.
        A continuación se presenta un ejercicio realizado por el estudiante.
        El bloque contiene la **Descripción del Problema** y la **Respuesta del Estudiante**.

        Tu tarea consiste en:
        1. Leer la descripción del problema para entender qué se pedía.
        2. Evaluar si la respuesta del estudiante satisface los requisitos planteados en la descripción.
        3. Asignar una calificación (0-10) y un comentario justificativo.

        Usa estrictamente esta rúbrica para asignar la calificación y guiar tu comentario:
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
        
        import json, re
        try:
            data = json.loads(response_text)
        except:
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            data = json.loads(match.group(0)) if match else {"calificación": 0, "comentario": "Error al procesar la evaluación del LLM"}

        nota = float(data.get("calificación", data.get("score", 0)))
        comentario = data.get("comentario", data.get("comment", "Sin comentarios."))

        with app.app_context():
            resp_record = RespuestaUsuario.query.get(respuesta_id)
            if resp_record:
                resp_record.llm_score = nota
                resp_record.llm_comment = comentario
                resp_record.status = "pending"
                db.session.commit()
                
                print(f"📝 Evaluado ID {respuesta_id}: {resp_record.llm_score}/10 - {comentario[:30]}...")
                color = "green" if nota >= 7 else "yellow" if nota >= 4 else "red"
                
                socketio.emit('student_activity', {
                    'type': 'answer',
                    'student_email': resp_record.correo_identificacion,
                    'status': color,
                    'score': nota,
                    'practice': resp_record.practice_name,
                    'problem_id': resp_record.problema_id,
                    'progress_pct': prog_pct,
                    'timestamp': dt.datetime.utcnow().isoformat(),
                    'answer_id': resp_record.id
                })
                
    except Exception as e:
        print(f"❌ Error en Auto-Grading: {e}")

# --- app.py (Helper functions section) ---
def calculate_sliding_window_color(student_email):
    """Calculates status color based on recent interaction history."""
    with app.app_context():
        since_time = dt.datetime.utcnow() - dt.timedelta(minutes=SEMAPHORE_WINDOW_MINUTES)
        
        # Fetch recent interactions for this student
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
            
            if any(flag in intent_lower for flag in RED_FLAG_INTENTS):
                red_count += 1
            elif any(flag in intent_lower for flag in YELLOW_FLAG_INTENTS):
                yellow_count += 1
                
        # Apply Heuristics (Priority: Red > Yellow > Green)
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
    nueva_respuesta = RespuestaUsuario(
        user_id=usuario.id,
        problema_id=problema_id,
        correo_identificacion=correo,
        respuesta=respuesta,
        practice_name=practice_name,
    )
    db.session.add(nueva_respuesta)
    db.session.commit()
    problem_text = get_problem_enunciado(practice_name, problema_id)
    thread = threading.Thread(
        target=auto_grade_answer,
        args=(nueva_respuesta.id, problem_text, respuesta, prog_pct)
    )
    thread.start()
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

    # 1. Save User Message ONCE and capture the ID
    chat_id = save_chat_turn(usuario, correo, practice_name, problema_id, "user", user_msg)

    # 2. Start Background LLM Response (Bot Reply)
    thread_bot = threading.Thread(
        target=background_llm_task,
        args=(app, usuario.id, correo, practice_name, problema_id)
    )
    thread_bot.start()
    
    # 3. Start Semaphore Analysis (using the chat_id from step 1)
    thread_analysis = threading.Thread(
        target=analyze_interaction_semaphore,
        args=(chat_id, user_msg, correo, prog_pct)
    )
    thread_analysis.start()

    return jsonify({"status": "processing", "message": "Procesando..."})
    
@app.route("/check_new_messages/<int:problema_id>", methods=["POST"])
def check_new_messages(problema_id):
    data = request.get_json()
    correo = data.get("correo_identificacion")
    last_msg = ChatLog.query.filter_by(
        correo_identificacion=correo, 
        problema_id=problema_id
    ).order_by(ChatLog.id.desc()).first()
    if last_msg and last_msg.role in ["assistant", "teacher"]:
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
        data = [get_exercise_metadata(f) for f in files]
        return jsonify(data), 200
    except Exception as e:
        print(f"Error listando ejercicios: {e}")
        return jsonify([]), 500
        
@app.route("/api/exercises/detail/<path:filename>", methods=["GET"])
@jwt_required()
def get_exercise_detail(filename):
    try:
        path = os.path.join(EXERCISES_PATH, filename)
        if not os.path.exists(path):
            return jsonify({"error": "Archivo no encontrado"}), 404
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data), 200
    except Exception as e:
        print(f"Error leyendo los detalles del ejercicio {filename}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/teacher/my-exercises", methods=["GET", "POST", "DELETE"])
@jwt_required()
def manage_my_exercises():
    prof_id = get_jwt_identity()
    
    if request.method == "GET":
        exs = ListaEjercicios.query.filter_by(profesor_id=prof_id).all()
        filenames = [e.exercise_filename for e in exs]
        data = [get_exercise_metadata(f) for f in filenames]
        return jsonify(data), 200
        
    if request.method == "POST":
        filename = request.get_json().get("filename")
        if not ListaEjercicios.query.filter_by(profesor_id=prof_id, exercise_filename=filename).first():
            db.session.add(ListaEjercicios(profesor_id=prof_id, exercise_filename=filename))
            db.session.commit()
        return jsonify({"msg": "Agregado"}), 200
        
    if request.method == "DELETE":
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

    # 1. Obtener la lista de MIS estudiantes
    student_records = ListaClase.query.filter_by(profesor_id=profesor_id).all()
    my_student_emails = [s.student_email for s in student_records]
    
    # 2. Obtener la lista de MIS tareas (ESTA ES LA CORRECCIÓN CLAVE)
    # Esto evita que veas tareas que el alumno hizo para otros profesores
    exercise_records = ListaEjercicios.query.filter_by(profesor_id=profesor_id).all()
    my_exercise_filenames = [e.exercise_filename for e in exercise_records]

    # Si no tienes estudiantes o no tienes tareas asignadas, no mostramos nada por seguridad
    if not my_student_emails or not my_exercise_filenames:
        return jsonify({"respuestas": [], "chats": []}), 200
    
    # 3. Determinar qué estudiantes consultar
    if target_student:
        # Validación de seguridad: ¿Este estudiante es mío?
        if target_student not in my_student_emails:
             return jsonify({"msg": "Acceso denegado a este estudiante"}), 403
        emails_to_query = [target_student]
    else:
        emails_to_query = my_student_emails

    # --- CONSULTA DE RESPUESTAS ---
    # Filtro base: Estudiantes míos Y Tareas mías
    resp_query = RespuestaUsuario.query.filter(
        RespuestaUsuario.correo_identificacion.in_(emails_to_query),
        RespuestaUsuario.practice_name.in_(my_exercise_filenames) # <--- FILTRO AGREGADO
    )
    
    # Filtro opcional: Tarea específica seleccionada en el dropdown
    if target_practice:
        # (Aunque el frontend envíe el nombre, el filtro base 'in_(my_exercise_filenames)' 
        # ya nos protege si intentan pedir una tarea ajena)
        resp_query = resp_query.filter(RespuestaUsuario.practice_name == target_practice)
    
    respuestas_db = resp_query.order_by(RespuestaUsuario.created_at.desc()).all()
    
    # --- CONSULTA DE CHATS ---
    # Filtro base: Estudiantes míos Y Tareas mías
    chat_query = ChatLog.query.filter(
        ChatLog.correo_identificacion.in_(emails_to_query),
        ChatLog.practice_name.in_(my_exercise_filenames) # <--- FILTRO AGREGADO
    )

    # Filtro opcional: Tarea específica
    if target_practice:
        chat_query = chat_query.filter(ChatLog.practice_name == target_practice)
        
    chats_db = chat_query.order_by(ChatLog.created_at.desc()).limit(500).all()

    # --- SERIALIZACIÓN (Igual que antes) ---
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
    
    return jsonify({
        "respuestas": respuestas_data,
        "chats": chat_data
    }), 200
    
@app.route("/api/teacher/all-users", methods=["GET"])
@jwt_required()
def get_all_registered_users():
    try:
        users = Usuario.query.all()
        emails = [u.correo_identificacion for u in users if u.correo_identificacion]
        return jsonify(emails), 200
    except Exception as e:
        print(f"Error fetching all users: {e}")
        return jsonify([]), 500
        
@app.route("/api/teacher/grades/pending", methods=["GET"])
@jwt_required()
def get_pending_grades():
    # Fetch answers that haven't been approved yet
    prof_id = get_jwt_identity()
    # (Optional: Filter by professor's students/exercises logic here)
    
    pending = RespuestaUsuario.query.filter(
        RespuestaUsuario.status == "pending"
    ).order_by(RespuestaUsuario.created_at.desc()).all()
    
    data = [{
        "id": r.id,
        "correo": r.correo_identificacion,
        "practica": r.practice_name,
        "problema_id": r.problema_id,
        "respuesta": r.respuesta,
        "llm_score": r.llm_score,
        "llm_comment": r.llm_comment
    } for r in pending]
    return jsonify(data), 200

@app.route("/api/teacher/grades/submit", methods=["POST"])
@jwt_required()
def submit_teacher_grade():
    data = request.get_json()
    resp_id = data.get("id")
    action = data.get("action") # "approve" or "edit"
    
    resp = RespuestaUsuario.query.get(resp_id)
    if not resp: return jsonify({"msg": "Not found"}), 404
    
    if action == "approve":
        resp.teacher_score = resp.llm_score
        resp.teacher_comment = resp.llm_comment
        resp.status = "approved"
    elif action == "edit":
        resp.teacher_score = float(data.get("score"))
        resp.teacher_comment = data.get("comment")
        resp.status = "edited"
        
    db.session.commit()
    return jsonify({"msg": "Grade updated"}), 200
    
@app.route("/api/teacher/status", methods=["GET"])
@jwt_required()
def get_student_statuses():
    # Returns the latest color for each student
    from sqlalchemy import func
    
    # Subquery to find the timestamp of the latest analysis per student
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
        chats = AnalisisInteraccion.query.filter_by(correo_identificacion=email).order_by(AnalisisInteraccion.created_at.desc()).limit(25).all()
        chat_events = [{
            'type': 'chat',
            'id': c.id,
            'timestamp': c.created_at.isoformat(),
            'intent': c.intent,
            'color': c.color_asignado,
            'description': f"Consultó al LLM: {c.intent}"
        } for c in chats]

        answers = RespuestaUsuario.query.filter_by(correo_identificacion=email).filter(RespuestaUsuario.status != 'processing').order_by(RespuestaUsuario.created_at.desc()).limit(25).all()
        answer_events = [{
            'type': 'answer',
            'id': a.id,
            'timestamp': a.created_at.isoformat() if a.created_at else dt.datetime.utcnow().isoformat(),
            'problem_id': a.problema_id,
            'score': a.llm_score,
            'color': "green" if (a.llm_score or 0) >= 7 else "yellow" if (a.llm_score or 0) >= 4 else "red",
            'description': f"Entregó Respuesta P{a.problema_id} (Calificación: {a.llm_score})"
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
# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------

if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False, allow_unsafe_werkzeug=True)
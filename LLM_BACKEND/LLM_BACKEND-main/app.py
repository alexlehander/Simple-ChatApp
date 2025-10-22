# app.py
# Backend for single-condition, open-ended answering flow
import os
import random
import string
import requests
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
PROBLEMAS: List[Dict] = [
    {"id": 1, "enunciado": "Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Escribe su matriz de adyacencia (Utiliza los enters para realizar el salto de linea)."},
    {"id": 2, "enunciado": "Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Escribe la lista de adyacencia."},
    {"id": 3, "enunciado": "Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Explica, con tus propias palabras, cuándo conviene usar cada representación (en qué tipo de algoritmo o tamaño de grafo."},
    {"id": 4, "enunciado": "Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Aplica el algoritmo BFS comenzando en el vértice 1, mostrando el orden en que se descubren los vértices y el padre de cada uno."},
    {"id": 5, "enunciado": "Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Indica qué distancia (en número de aristas) tiene cada vértice desde el vertice 1."},
    {"id": 6, "enunciado": "Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Describe, con tus propias palabras, una aplicación práctica de BFS en la vida real o en informática."},
    {"id": 7, "enunciado": "Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Ejecuta DFS(G) considerando el orden alfabético de los vértices y anota para cada vértice los tiempos de descubrimiento (d) y finalización (f)."},
    {"id": 8, "enunciado": "Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Determina si el grafo contiene algún ciclo con base en los tiempos d/f."},
    {"id": 9, "enunciado": "Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Explica, con tus propias palabras, qué diferencia conceptual hay entre BFS y DFS."},
    {"id": 10, "enunciado": "Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Usa el algoritmo de DFS para obtener un orden topológico de los vértices, escribiendo los pasos clave (descubrimiento y finalización) y el resultado final."},
    {"id": 11, "enunciado": "Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Verifica tu orden topológico comprobando que todas las aristas van de izquierda a derecha."},
    {"id": 12, "enunciado": "Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Explica una aplicación real de orden topológico, por ejemplo en planificación de tareas o compilación de programas."},
    {"id": 13, "enunciado": "Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Usa el algoritmo de Kosaraju o Tarjan (como en Cormen) para identificar los componentes fuertemente conectados (CFCs), mostrando los pasos principales (Primer DFS con tiempos de finalización, Grafo transpuesto, Segundo DFS por orden decreciente de f)."},
    {"id": 14, "enunciado": "Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Escribe los CFCs encontradas en forma de conjuntos (por ejemplo {A,B,C})."},
    {"id": 15, "enunciado": "Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Explica brevemente qué significa que dos vértices pertenezcan al mismo CFC."},
    {"id": 16, "enunciado": "Comparación de representaciones de grafos -> Supón que tienes un grafo no dirigido y muy denso, con n = 10,000 vértices, y otro dirigido y disperso, con n = 10,000 pero solo 20,000 aristas... Explica qué representación (lista o matriz de adyacencia) sería más eficiente para cada grafo y por qué."},
    {"id": 17, "enunciado": "Comparación de representaciones de grafos -> Supón que tienes un grafo no dirigido y muy denso, con n = 10,000 vértices, y otro dirigido y disperso, con n = 10,000 pero solo 20,000 aristas... Calcula aproximadamente cuánta memoria necesitaría cada representación si los vértices se numeran del 1 al n (usa la fórmula n² para matriz y 2m o m para listas, según el caso)."},
    {"id": 18, "enunciado": "BFS con rutas más cortas -> Se tiene una red de transporte urbano simplificada. Los vértices representan paradas de autobús, y las aristas indican que hay una conexión directa entre ellas: V = {Centro, Museo, Parque, Escuela, Estadio, Hospital}, E = {(Centro,Museo), (Centro,Parque), (Museo,Escuela), (Parque,Estadio), (Escuela,Hospital), (Estadio,Hospital)}... Explica brevemente por qué BFS siempre encuentra el camino más corto en este tipo de grafo."},
    # ... agrega más ...
]

# System prompts per problem (optional). If missing, a generic prompt is used.
PROMPTS_PROBLEMAS: Dict[int, str] = {
    1: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Escribe su matriz de adyacencia (Utiliza los enters para realizar el salto de linea).",
    2: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Escribe la lista de adyacencia.",
    3: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Listas de adyacencia y matrices de adyacencia -> Dado el siguiente grafo dirigido con vértices V = {A, B, C, D, E} y aristas E = {(A,B), (A,C), (B,D), (C,D), (D,E), (E,A)}... Explica, con tus propias palabras, cuándo conviene usar cada representación (en qué tipo de algoritmo o tamaño de grafo.",
    4: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Aplica el algoritmo BFS comenzando en el vértice 1, mostrando el orden en que se descubren los vértices y el padre de cada uno.",
    5: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Indica qué distancia (en número de aristas) tiene cada vértice desde el vertice 1.",
    6: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en anchura (Breadth-First Search) -> Se tiene el grafo no dirigido siguiente: V = {1, 2, 3, 4, 5, 6}, E = {(1,2), (1,3), (2,4), (3,5), (4,6), (5,6)}... Describe, con tus propias palabras, una aplicación práctica de BFS en la vida real o en informática.",
    7: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Ejecuta DFS(G) considerando el orden alfabético de los vértices y anota para cada vértice los tiempos de descubrimiento (d) y finalización (f).",
    8: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Determina si el grafo contiene algún ciclo con base en los tiempos d/f.",
    9: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Búsqueda en profundidad (Depth-First Search) -> Considera el siguiente grafo dirigido: V = {u, v, w, x, y, z}, E = {(u,v), (u,x), (v,y), (w,y), (w,z), (x,v), (y,x), (z,z)}... Explica, con tus propias palabras, qué diferencia conceptual hay entre BFS y DFS.",
    10: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Usa el algoritmo de DFS para obtener un orden topológico de los vértices, escribiendo los pasos clave (descubrimiento y finalización) y el resultado final.",
    11: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Verifica tu orden topológico comprobando que todas las aristas van de izquierda a derecha.",
    12: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Orden topológico (Topological Sort) -> Dado el siguiente grafo dirigido acíclico (DAG): V = {A, B, C, D, E, F}, E = {(A,B), (A,C), (B,D), (C,D), (C,E), (D,F), (E,F)}... Explica una aplicación real de orden topológico, por ejemplo en planificación de tareas o compilación de programas.",
    13: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Usa el algoritmo de Kosaraju o Tarjan (como en Cormen) para identificar los componentes fuertemente conectados (CFCs), mostrando los pasos principales (Primer DFS con tiempos de finalización, Grafo transpuesto, Segundo DFS por orden decreciente de f).",
    14: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Escribe los CFCs encontradas en forma de conjuntos (por ejemplo {A,B,C}).",
    15: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Componentes fuertemente conectados (Strongly Connected Components) -> Considera el siguiente grafo dirigido: V = {A, B, C, D, E, F}, E = {(A,B), (B,C), (C,A), (B,D), (D,E), (E,F), (F,D)}... Explica brevemente qué significa que dos vértices pertenezcan al mismo CFC.",
    16: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Comparación de representaciones de grafos -> Supón que tienes un grafo no dirigido y muy denso, con n = 10,000 vértices, y otro dirigido y disperso, con n = 10,000 pero solo 20,000 aristas... Explica qué representación (lista o matriz de adyacencia) sería más eficiente para cada grafo y por qué.",
    17: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: Comparación de representaciones de grafos -> Supón que tienes un grafo no dirigido y muy denso, con n = 10,000 vértices, y otro dirigido y disperso, con n = 10,000 pero solo 20,000 aristas... Calcula aproximadamente cuánta memoria necesitaría cada representación si los vértices se numeran del 1 al n (usa la fórmula n² para matriz y 2m o m para listas, según el caso).",
    18: "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario (TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario). RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada. El usuario en cuestion esta trabajando con el siguiente problema: BFS con rutas más cortas -> Se tiene una red de transporte urbano simplificada. Los vértices representan paradas de autobús, y las aristas indican que hay una conexión directa entre ellas: V = {Centro, Museo, Parque, Escuela, Estadio, Hospital}, E = {(Centro,Museo), (Centro,Parque), (Museo,Escuela), (Parque,Estadio), (Escuela,Hospital), (Estadio,Hospital)}... Explica brevemente por qué BFS siempre encuentra el camino más corto en este tipo de grafo."
}

DEFAULT_SYSTEM_PROMPT = (
    "Eres un tutor inteligente que emplea el método “Chain of Thought” para procesar la información y responder en español de manera socrática. "
    "BAJO NINGUNA CIRCUNSTANCIA puedes generar una solución completa o parcial al ejercicio con el que está trabajando el usuario. "
    "TAMPOCO tienes permitido responder preguntas o generar información que se sale del contexto del ejercicio con el que está trabajando el usuario. "
    "RESPONDES a las preguntas del usuario con frases breves y precisas, evitando redundancia y lenguaje excesivamente formal. "
    "DEBES ayudar al usuario a comprender el tema proporcionando explicaciones, creando ejemplos, y clarificando conceptos. "
    "Si ves que el usuario tiene dificultades, ayudalo con pistas graduales y retroalimentación personalizada."
)

# ------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------
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

def history_for_chat(correo_identificacion: str | None, problema_id: int) -> List[Dict]:
    logs = (ChatLog.query
            .filter_by(correo_identificacion=correo_identificacion, problema_id=problema_id)
            .order_by(ChatLog.created_at.asc())
            .all())
    messages = []
    # Prepend a system message
    sys_prompt = PROMPTS_PROBLEMAS.get(problema_id, DEFAULT_SYSTEM_PROMPT)
    messages.append({"role": "system", "content": sys_prompt})
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

@app.route("/obtener_problema/<int:problema_id>", methods=["GET"])
def obtener_problema(problema_id: int):
    """Serve problems as open-ended only (no options)."""
    problema = next((p for p in PROBLEMAS if p["id"] == problema_id), None)
    if not problema:
        return jsonify({"error": "Problema no encontrado"}), 404
    payload = {
        "id": problema["id"],
        "enunciado": problema["enunciado"],
        "tipo": "texto"  # force open-ended on the frontend
    }
    return jsonify(payload)

@app.route("/verificar_respuesta/<int:problema_id>", methods=["POST"])
def verificar_respuesta(problema_id):
    data = request.get_json()
    respuesta = data.get("respuesta")
    correo = data.get("correo_identificacion")

    if not respuesta or not correo:
        return jsonify({"error": "Datos incompletos"}), 400

    usuario = get_or_create_user(correo)

    nueva_respuesta = RespuestaUsuario(
        user_id=usuario.id,
        problema_id=problema_id,
        correo_identificacion=correo,
        respuesta=respuesta,
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
    codigo_identificacion = (data.get("codigo_identificacion") or "").strip()

    if not user_msg:
        return jsonify({"response": "¿Puedes escribir tu mensaje?"})

    usuario = get_or_create_user(codigo_identificacion or None)

    # Save user's turn
    save_chat_turn(usuario, codigo_identificacion or None, problema_id, "user", user_msg)

    # Build message history (system + prior turns)
    messages = history_for_chat(codigo_identificacion or None, problema_id)

    # Append current user message (again for the actual call)
    messages.append({"role": "user", "content": user_msg})

    # If we don't have an API key, return a graceful fallback
    if not OPENROUTER_API_KEY:
        assistant_text = (
            "Gracias por tu mensaje. En este momento no puedo contactar al tutor automático. "
            "Intenta explicar tu razonamiento y da el siguiente paso en el problema."
        )
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
        save_chat_turn(usuario, codigo_identificacion or None, problema_id, "assistant", assistant_text)
        return jsonify({"response": assistant_text})

@app.route("/contar_problemas", methods=["GET"])
def contar_problemas():
    return jsonify({"total": len(PROBLEMAS)})
# ------------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    # For local dev; in production, gunicorn runs this app
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)

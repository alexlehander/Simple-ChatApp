import flet as ft
import requests
import time
import threading
import os
import json

EXERCISES_PATH = "exercises"

#COLORES = {
#    # Fondos y superficies
#    "fondo": "#F5F7FA",         # gris-azulado muy claro (base neutra)
#    "accento": "#E8F1FA",       # azul pastel para tarjetas / paneles
#
#    # Colores de texto
#    "texto": "#1E2A38",         # gris-azul oscuro, alto contraste
#    "subtitulo": "#4E5D6C",     # gris medio, ideal para instrucciones y detalles
#
#    # Colores principales de interacción
#    "primario": "#1A4E8A",      # azul profesional, más cálido que el marino puro
#    "secundario": "#5BA3D0",    # azul claro moderno para áreas intermedias
#    "boton": "#1A4E8A",         # igual que primario para consistencia
#    "borde": "#C8D6E5",         # gris azulado claro para contornos suaves
#
#    # Estados del sistema
#    "exito": "#2E8B57",         # verde esmeralda legible (feedback positivo)
#    "error": "#D64541",         # rojo coral (mejor contraste que #e63946)
#    "advertencia": "#E0A800",   # amarillo dorado para alertas suaves
#
#    # Acentos (para resaltar)
#    "acento": "#FFB400",        # dorado para llamar la atención sin saturar
#    "acento2": "#E25B50",       # coral suave (resaltar textos o etiquetas)
#}

COLORES = {
    # Fondos y superficies (más neutros)
    "fondo":     "#0B0F14",  # charcoal neutral (menos tinte azul que #0F172A)
    "accento":   "#161A20",  # panel/cards (ligeramente más claro que fondo)

    # Texto
    "texto":     "#E6E9EF",  # gris muy claro, no blanco puro
    "subtitulo": "#AAB3C0",  # gris medio neutro

    # Interacción (azules que destacan más sobre fondo neutro)
    "primario":  "#8FB7FF",  # azul claro un poco más cálido (↑ contraste)
    "secundario":"#5B96F7",  # azul medio para inputs/áreas intermedias
    "boton":     "#1F3B86",  # azul profundo, suficiente separación del fondo
    "borde":     "#2B323A",  # gris neutro para contornos/sombras suaves

    # Estados
    "exito":     "#2ECC95",  # verde jade ligeramente más frío
    "error":     "#F2797B",  # rojo suave legible en dark
    "advertencia":"#F6A721", # ámbar accesible

    # Acentos
    "acento":    "#F5BE3D",  # dorado cálido para highlights
    "acento2":   "#F4788A",  # coral para etiquetas/pequeños énfasis
}

JS_CLEAR_STORAGE = (
    "javascript:(() => {"
    "  try {"
    "    localStorage && localStorage.clear && localStorage.clear();"
    "    sessionStorage && sessionStorage.clear && sessionStorage.clear();"
    "    if (window.indexedDB) {"
    "      if (indexedDB.databases) {"
    "        indexedDB.databases().then(dbs => dbs.forEach(db => indexedDB.deleteDatabase(db.name)));"
    "      } else {"
    "        ['_flet', 'flet_client_storage'].forEach(n => { try { indexedDB.deleteDatabase(n); } catch(e){} });"
    "      }"
    "    }"
    "  } catch(e) { console.error('Error clearing storage', e); }"
    "  finally { location.reload(); }"
    "})();"
)

BASE = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_CHAT              = f"{BASE}/chat"
BACKEND_URL_VERIFICAR         = f"{BASE}/verificar_respuesta"

# ---- Persistence helpers (top of file) ----
STATE_KEYS = {
    "screen": "ui_screen",                     # "consent", "instructions", "survey", "problems", "final"
    "code": "correo_identificacion",           # you already use this key
    "current_problem": "current_problem_id",   # int
    "answers": "answers_map",                  # dict: {problem_id: "answer text"}
    "chat": "chat_map",                        # dict: {problem_id: [{"role":"user|agent","text":"..."}]}
    "timer_start": "timer_start_epoch",        # int epoch seconds when Xmin started
}

def listar_sesiones():
    #Returns a list of available session files
    try:
        return [f for f in os.listdir(EXERCISES_PATH) if f.endswith(".json")]
    except FileNotFoundError:
        return []

def cargar_sesion(nombre_archivo):
    #Loads a specific session file (list of problems)
    try:
        with open(os.path.join(EXERCISES_PATH, nombre_archivo), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("title", nombre_archivo), data.get("problemas", [])
    except Exception as e:
        print(f"⚠️ Error al cargar sesión {nombre_archivo}: {e}")
        return nombre_archivo, []

def save_k(page, k, v):
    page.client_storage.set(k, v)

def load_k(page, k, default=None):
    try:
        v = page.client_storage.get(k)
        return v if v is not None else default
    except Exception:
        return default

def update_map(page, key, problem_id, item):
    m = load_k(page, key, {}) or {}
    pid = str(problem_id)
    if key == STATE_KEYS["answers"]:
        m[pid] = item  # item is text
    elif key == STATE_KEYS["chat"]:
        m.setdefault(pid, []).append(item)  # item is {"role": "...", "text": "..."}
    save_k(page, key, m)

def reset_progress(page):
    try:
        keys = list(page.client_storage.get_keys(""))
        print(f"🧹 Eliminando {len(keys)} claves del almacenamiento local...")
        for k in keys:
            try:
                page.client_storage.remove(k)
            except Exception as err:
                print(f"⚠️ No se pudo borrar clave {k}: {err}")
        if hasattr(page, "_is_loading_problem"):
            delattr(page, "_is_loading_problem")
        page.clean()
        page.update()
        try:
            page.session.clear()
        except Exception:
            pass
        print("✅ Limpieza interna de Flet completada.")
    except Exception as e:
        print("❌ Error durante reset_progress:", e)

def main(page: ft.Page):
    page.title = "Grow Together"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START  # 👈 pin everything to the top
    page.scroll = ft.ScrollMode.ALWAYS
    page.padding = 20
    page.bgcolor = COLORES["fondo"]
    page.theme_mode = ft.ThemeMode.DARK #ft.ThemeMode.LIGHT
    
    page.theme = ft.Theme(
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color={"default": COLORES["primario"]},
            track_color={"default": COLORES["borde"]},
            thickness=10,
            radius=10,
        )
    )
    
    # Global snack (Saved)
    save_snack = ft.SnackBar(
        content=ft.Text("Respuesta guardada", color=COLORES["accento"]),
        bgcolor=COLORES["exito"], open=False, duration=1000
    )
    
    def flash(msg: str, ok: bool = False, ms: int = 2000):
        save_snack.content = ft.Text(msg, color=COLORES["accento"])
        save_snack.bgcolor = COLORES["exito"] if ok else COLORES["error"]
        save_snack.duration = ms
        save_snack.open = True
        page.update()
    
    page.overlay.append(save_snack)
    
    # =============== PANTALLA 1: CONSENTIMIENTO =============== 
    def mostrar_pantalla_consentimiento():
        save_k(page, STATE_KEYS["screen"], "consent")
        page.scroll = ft.ScrollMode.ALWAYS
        
        title = ft.Text(
            "¿Listo(a) para resolver tus prácticas/exámenes con ayuda de un tutor inteligente?",
            size=24, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER,
        )
        
        subtitle = ft.Text(
            "Puedes usar tus apuntes (texto o digital) y buscar en el navegador. Tienes prohibido usar chatbots (ChatGPT, LLaMa, etc.) o platicar con tus compañeros.",
            size=20, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        
        details = ft.Text(
            "Sólo se recolectarán datos relacionados con tu interacción con el tutor inteligente, no información personal.",
            size=16, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        
        aceptar_btn = ft.ElevatedButton(
            "Continuar",
            disabled=True,
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=lambda e: mostrar_pantalla_seleccion_sesion(),
        )
        
        def on_check(e):
            aceptar_btn.disabled = not e.control.value
            page.update()
        
        checkbox = ft.Checkbox(
            label="Doy mi consentimiento informado",
            on_change=on_check,
            active_color=COLORES["primario"],
            check_color=COLORES["accento"],
            overlay_color=COLORES["acento2"],
            label_style=ft.TextStyle(color=COLORES["primario"]),
        )
        
        checkbox_centered = ft.Row(
            [checkbox],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        
        layout = ft.Column(
            [title, ft.Divider(20),
            subtitle, ft.Divider(20),
            details, ft.Divider(20),
            checkbox_centered,
            aceptar_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )
        
        container = ft.Container(
            content=layout,
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            shadow=ft.BoxShadow(blur_radius=10, color=COLORES["borde"]),
            width=600,
            expand=True,
        )
        
        page.clean()
        page.add(container)
        
    # =============== PANTALLA 2: INSTRUCCIONES =============== 
    def mostrar_pantalla_seleccion_sesion():
        save_k(page, STATE_KEYS["screen"], "instructions")
        page.clean()
        archivos = listar_sesiones()

        if not archivos:
            page.add(ft.Text("No hay sesiones disponibles en la carpeta 'exercises/'.", color=ft.colors.RED))
            return

        opciones = [ft.dropdown.Option(a) for a in archivos]

        email_input = ft.TextField(
            label=ft.Container(
                content=ft.Text("Correo institucional", text_align=ft.TextAlign.CENTER),
                alignment=ft.alignment.center
            ),
            hint_text="nombre@uabc.edu.mx",
            width=400,
            text_align=ft.TextAlign.CENTER,
            color=COLORES["texto"],
            bgcolor=COLORES["accento"],
            border_color=COLORES["borde"],
        )

        def on_change_sesion(e):
            nombre_archivo = e.control.value
            if not nombre_archivo:
                return
            try:
                with open(os.path.join(EXERCISES_PATH, nombre_archivo), "r", encoding="utf-8") as f:
                    data = json.load(f)
                descripcion = data.get("description", "No se encontró descripción para esta práctica.")
                descripcion_text.value = descripcion
                page.update()
            except Exception as err:
                print(f"⚠️ Error al leer descripción de {nombre_archivo}: {err}")

        # 🔹 crea el Dropdown ANTES de iniciar_sesion
        sesion_dropdown = ft.Dropdown(
            label="Selecciona una actividad para resolver",
            options=opciones,
            width=400,
            on_change=on_change_sesion,
        )
        
        descripcion_label = ft.Text(
            "Descripción de la práctica:",
            size=18, weight="bold", color=COLORES["primario"]
        )

        descripcion_text = ft.Text(
            "Selecciona una práctica para ver su descripción.",
            color=COLORES["texto"], size=16, text_align=ft.TextAlign.JUSTIFY
        )
        
        def iniciar_sesion(e):
            correo = email_input.value.strip()
            nombre_archivo = sesion_dropdown.value
            if "@" not in correo:
                flash("Ingresa un correo válido")
                return
            if not nombre_archivo:
                flash("Selecciona una actividad antes de continuar")
                return

            page.client_storage.set("correo_identificacion", correo)
            titulo, problemas = cargar_sesion(nombre_archivo)
            save_k(page, "selected_session_title", titulo)
            save_k(page, "selected_session_problems", problemas)
            save_k(page, "selected_session_filename", nombre_archivo)
            mostrar_pantalla_intervencion(titulo, problemas)

        iniciar_button = ft.ElevatedButton(
            "Comenzar la actividad",
            icon=ft.Icons.PLAY_ARROW,
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=iniciar_sesion,
        )

        layout = ft.Column(
            [
                ft.Text(
                    "Inicia sesión con tu correo institucional y selecciona una actividad de la lista",
                    size=22, weight="bold", color=COLORES["primario"]
                ),
                email_input,
                sesion_dropdown,
                descripcion_label,
                descripcion_text,
                iniciar_button,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )

        page.add(ft.Container(content=layout, padding=30, bgcolor=COLORES["accento"], border_radius=10))

    # =============== PANTALLA 4: INTERVENCIÓN (CHAT + PROBLEMAS) ===============
    def mostrar_pantalla_intervencion(titulo_sesion, PROBLEMAS):
        save_k(page, STATE_KEYS["screen"], "problems")

        correo = page.client_storage.get("correo_identificacion") or "No disponible"
        stop_timer = False
        problema_actual_id = 1
        NUM_PROBLEMAS = len(PROBLEMAS)

        # --- Align completion flags length with current total ---
        prev = load_k(page, "respuestas_enviadas", [])
        if not isinstance(prev, list) or len(prev) != NUM_PROBLEMAS:
            respuestas_enviadas = [False] * NUM_PROBLEMAS
        else:
            respuestas_enviadas = prev
        save_k(page, "respuestas_enviadas", respuestas_enviadas)

        # === PROGRESS BAR OF PROBLEMS ===
        def construir_barra_progreso():
            progress_squares = []
            for i in range(1, NUM_PROBLEMAS + 1):
                color = COLORES["primario"] if i == problema_actual_id else (
                    COLORES["exito"] if respuestas_enviadas[i - 1] else COLORES["advertencia"]
                )
                square = ft.Container(
                    width=25,
                    height=25,
                    bgcolor=color,
                    ink=True,  # enables hover ink ripple
                    border=ft.border.all(1, COLORES["borde"]),
                    border_radius=5,
                    alignment=ft.alignment.center,
                    content=ft.Text(str(i), size=12, color=COLORES["fondo"], weight="bold"),
                    tooltip=f"Problema {i}: {'Entregado' if respuestas_enviadas[i - 1] else 'Pendiente'}",
                    on_click=lambda e, pid=i: (
                        None if getattr(page, "_is_loading_problem", False)
                        else cargar_problema(pid)
                    )
                )
                progress_squares.append(square)
            return ft.Row(progress_squares, spacing=5, alignment=ft.MainAxisAlignment.CENTER)

        barra_progreso = construir_barra_progreso()

        def guardar_respuesta_actual():
            #Guarda el texto actual antes de cambiar de problema.
            if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                texto = (respuesta_container.controls[0].value or "").strip()
                save_k(page, f"respuesta_{problema_actual_id}", texto)

        def cargar_chat_guardado(id_problema):
            #Recupera el historial del chat de un problema.
            chat_area.controls.clear()
            chats = load_k(page, STATE_KEYS["chat"], {})
            for msg in chats.get(str(id_problema), []):
                align = ft.MainAxisAlignment.END if msg["role"] == "user" else ft.MainAxisAlignment.START
                text_color = COLORES["error"] if msg["role"] == "user" else COLORES["texto"]
                chat_area.controls.append(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(msg["text"], color=text_color, size=16, selectable=True),
                                width=400,   # ✅ limit line width
                                alignment=ft.alignment.top_right if msg["role"] == "user" else ft.alignment.top_left,
                            )
                        ],
                        alignment=align,
                    )
                )
            chat_area.update()

        # 🔹 Restore last open problem
        saved_id = load_k(page, STATE_KEYS["current_problem"], 1)
        problema_actual_id = int(saved_id)

        # ---- Funciones internas ----
        def cargar_problema(id_problema: int):
            nonlocal problema_actual_id
            problema_actual_id = id_problema
            save_k(page, STATE_KEYS["current_problem"], problema_actual_id)
            chat_area.controls.clear()

            siguiente_button.disabled = False
            enviar_button.disabled = False
            retroceder_button.disabled = False
            page.update()

            if getattr(page, "_is_loading_problem", False):
                return

            page._is_loading_problem = True
            try:
                p = next((pr for pr in PROBLEMAS if pr.get("id") == id_problema), None)
                if not p:
                    feedback_text.value = "No se encontró el problema en la sesión seleccionada."
                    feedback_text.color = COLORES["error"]
                    page.update()
                    return

                # ✅ Cargar enunciado localmente
                ejercicio_text.value = p.get("enunciado", "")
                ejercicio_text.text_align = ft.TextAlign.JUSTIFY

                # ✅ Crear campo de respuesta
                respuesta_container.controls.clear()
                tf = ft.TextField(
                    hint_text="Escribe tu respuesta aquí, presionando «Enter» para salto de línea",
                    expand=True, multiline=True, min_lines=1, max_lines=5,
                    bgcolor=COLORES["secundario"], border_color=COLORES["secundario"],
                    focused_border_color=COLORES["primario"], border_radius=15,
                    hint_style=ft.TextStyle(color=COLORES["accento"]),
                    on_change=lambda e: save_k(page, f"respuesta_{id_problema}", e.control.value)
                )

                draft = page.client_storage.get(f"respuesta_{id_problema}")
                if draft:
                    tf.value = draft
                respuesta_container.controls.append(tf)

                feedback_text.value = ""
                status_row.visible = False

            except Exception as e:
                feedback_text.value = "Error al cargar el problema."
                feedback_text.color = COLORES["error"]
                print(f"[WARN] Error cargando problema {id_problema}: {e}")
            finally:
                page._is_loading_problem = False
                cargar_chat_guardado(id_problema)
                numero_text.value = f"Problema: {id_problema} de {NUM_PROBLEMAS}"
                estado = "✅ Entregado" if respuestas_enviadas[id_problema - 1] else "⏳ Pendiente"
                estado_text.value = f"Estado: {estado}"
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Completados: {entregados} de {NUM_PROBLEMAS}"
                barra_progreso.controls.clear()
                barra_progreso.controls.extend(construir_barra_progreso().controls)
                page.update()

        def ir_a_problema(delta):
            nonlocal problema_actual_id
            guardar_respuesta_actual()
            nuevo_id = problema_actual_id + delta

            # ⛔ Si intenta ir antes del primer problema
            if nuevo_id < 1:
                feedback_text.value = "¡Estás en el primer problema!"
                feedback_text.color = COLORES["advertencia"]
                page.update()
                return

            # ⛔ Si intenta ir después del último problema
            if nuevo_id > NUM_PROBLEMAS:
                if all(respuestas_enviadas):
                    stop_timer = True
                    mostrar_pantalla_encuesta_final()
                else:
                    feedback_text.value = "¡Aún tienes problemas pendientes por contestar!"
                    feedback_text.color = COLORES["advertencia"]
                    page.update()
                return

            cargar_problema(nuevo_id)

        def enviar_respuesta(e):
            if getattr(page, "_is_sending_response", False):
                return
            page._is_sending_response = True
            nonlocal problema_actual_id, stop_timer
            enviar_button.disabled = True
            page.update()

            try:
                val = ""
                if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                    val = (respuesta_container.controls[0].value or "").strip()
                if not val:
                    feedback_text.value = "La respuesta no puede estar vacía."
                    feedback_text.color = COLORES["error"]
                    enviar_button.disabled = False
                    page.update()
                    return

                practice_name = load_k(page, "selected_session_filename", "unknown_session.json")
                resp = requests.post(
                    f"{BACKEND_URL_VERIFICAR}/{problema_actual_id}",
                    json={
                        "respuesta": val,
                        "correo_identificacion": correo,
                        "practice_name": practice_name
                    },
                    timeout=20,
                )

                resp.raise_for_status()

                # ✅ Guardar y avanzar de forma segura
                save_k(page, f"respuesta_{problema_actual_id}", val)
                respuestas_enviadas[problema_actual_id - 1] = True
                save_k(page, "respuestas_enviadas", respuestas_enviadas)
                # 🔄 Refrescar rótulos de Estado / Progreso
                estado_text.value = "Estado: ✅ Entregado"
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Completados: {entregados} de {NUM_PROBLEMAS}"
                feedback_text.value = ""
                save_snack.open = True
                status_icon.visible = True
                status_text.value = "Guardado"
                status_row.visible = True
                # 🔄 Refresh progress bar colors
                barra_progreso.controls.clear()
                barra_progreso.controls.extend(construir_barra_progreso().controls)
                page.update()
                threading.Timer(1.2, lambda: (setattr(status_row, "visible", False), page.update())).start()

                # --- Verificar existencia del siguiente problema ---
                next_id = problema_actual_id + 1
                if next_id <= NUM_PROBLEMAS:
                    save_k(page, STATE_KEYS["current_problem"], next_id)
                    cargar_problema(next_id)
                else:
                    feedback_text.value = "¡Este fue el último problema disponible, presiona «Siguiente» para finalizar si ya entregaste todo!"
                    feedback_text.color = COLORES["advertencia"]
                    enviar_button.disabled = False
                    page.update()

            except Exception:
                feedback_text.value = "Error al registrar o cargar el siguiente problema."
                feedback_text.color = COLORES["error"]
                enviar_button.disabled = False
                page.update()
            finally:
                # ✅ Siempre desbloquear
                page._is_sending_response = False

        # ---- Chat UI ----
        chat_area = ft.ListView(
            spacing=20,
            padding=20,
            height=475,
            auto_scroll=True,
        )

        chat_container = ft.Container(
            content=chat_area,
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            height=475,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        def send_message(e):
            msg = (user_input.value or "").strip()
            if not msg:
                chat_area.controls.append(
                    ft.Container(
                        content=ft.Text("Por favor, escribe un mensaje", color=COLORES["error"], size=16),
                        padding=20, bgcolor=ft.colors.RED_50, border_radius=10,
                        alignment = ft.alignment.center,
                    )
                )
                page.update()
                return

            # Show user bubble
            chat_area.controls.append(
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(msg, color=COLORES["error"], size=16, selectable=True),
                            width=400,   # ✅ same width constraint
                            alignment=ft.alignment.top_right,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                )
            )
            user_input.value = ""
            page.update()
            
            update_map(page, STATE_KEYS["chat"], problema_actual_id, {"role": "user", "text": msg})
            save_k(page, STATE_KEYS["chat"], load_k(page, STATE_KEYS["chat"], {}))  # ensure persisted
            # ✅ Define un default para evitar NameError si hay excepción
            data = {"response": "Sin respuesta"}

            # Call backend
            try:
                r = requests.post(
                    f"{BACKEND_URL_CHAT}/{problema_actual_id}",
                    json={
                        "message": msg,
                        "correo_identificacion": correo,
                        "practice_name": load_k(page, "selected_session_filename", "unknown_session.json")
                    },
                    timeout=30,
                )
                data = r.json() if r.ok else {"response": "Sin respuesta"}
                chat_area.controls.append(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(data.get("response", "Sin respuesta"), color=COLORES["texto"], size=16, selectable=True),
                                width=400,   # ✅ same wrapping limit
                                alignment=ft.alignment.top_left,
                            )
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    )
                )
                chat_area.auto_scroll = True
                chat_area.update()
                chat_area.auto_scroll = False
            except Exception:
                chat_area.controls.append(
                    ft.Row(
                        [ft.Container(
                            content=ft.Text("Error de conexión con el servidor.", color=COLORES["accento"]),
                            bgcolor=COLORES["error"],
                            padding=20,
                            border_radius=10
                        )],
                        alignment=ft.MainAxisAlignment.START,
                    )
                )
            page.update()
            
            update_map(page, STATE_KEYS["chat"], problema_actual_id, {"role": "assistant", "text": data.get('response','Sin respuesta')})
            save_k(page, STATE_KEYS["chat"], load_k(page, STATE_KEYS["chat"], {}))

        user_input = ft.TextField(
            hint_text="Presiona «Enter» para enviar tu mensaje",
            bgcolor=COLORES["secundario"],
            border_color=COLORES["secundario"],
            focused_border_color=COLORES["primario"],
            border_radius=10,
            hint_style=ft.TextStyle(color=COLORES["accento"]),
            max_length=1000,
            on_submit=send_message,
        )

        # ---- Problem area ----
        ejercicio_text = ft.Text("Aquí aparecerá el enunciado del problema", size=20, color=COLORES["primario"], weight="bold")
        respuesta_container = ft.Column(spacing=20)
        feedback_text = ft.Text("", size=16, color=COLORES["exito"], text_align=ft.TextAlign.CENTER)
        status_icon = ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=COLORES["exito"], size=18, visible=False)
        status_text = ft.Text("", size=12, color=COLORES["exito"])
        status_row = ft.Row([status_icon, status_text], spacing=10, visible=False)

        retroceder_button = ft.ElevatedButton(
            "⏪ Anterior",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=lambda e: ir_a_problema(-1)
        )

        enviar_button = ft.ElevatedButton(
            "Guardar ✅ Respuesta",
            bgcolor=COLORES["exito"],
            color=COLORES["accento"],
            on_click=enviar_respuesta
        )

        siguiente_button = ft.ElevatedButton(
            "Siguiente ⏩",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=lambda e: ir_a_problema(+1)
        )

        botones_row = ft.Row(
            [retroceder_button, enviar_button, siguiente_button],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=20
        )

        numero_text = ft.Text(
            f"Problema: {problema_actual_id} de {NUM_PROBLEMAS}",
            color=COLORES["subtitulo"],
            size=14
        )
        
        estado_text = ft.Text(
            "",
            size=14,
            color=COLORES["subtitulo"]
        )
        
        progreso_text = ft.Text(
            "",
            size=14,
            color=COLORES["subtitulo"]
        )
        
        titulo_label = ft.Text(
            f"{titulo_sesion}",
            size=20, color=COLORES["subtitulo"], weight="bold",
        )
        
        # (opcional) pre-inicializar antes del primer cargar_problema:
        estado_text.value = "Estado: ⏳ Pendiente"
        progreso_text.value = f"Completados: {sum(1 for x in respuestas_enviadas if x)} de {NUM_PROBLEMAS}"
        
        problemas_area = ft.Column(
            [
                numero_text,
                estado_text,
                progreso_text,
                ejercicio_text,
                respuesta_container,
                botones_row,
                feedback_text,
                status_row,
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # Layout
        temporizador_text = ft.Text("", size=32, color=COLORES["primario"], weight="bold", text_align=ft.TextAlign.CENTER)
        
        left_panel = ft.Container(
            content=ft.Column([chat_container, user_input], spacing=20, expand=True),
            expand=1,
        )
        
        right_panel = ft.Container(
            content=ft.Container(
                content=problemas_area,
                padding=20,
                bgcolor=COLORES["accento"],
                border_radius=10,
                expand=True,
            ),
            expand=1,
        )
        
        main_row = ft.Row(
            [left_panel, right_panel],
            spacing=20,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        
        def reiniciar_practica(e):
            try:
                nonlocal stop_timer
                stop_timer = True
            except Exception:
                pass
            reset_progress(page)
            try:
                page.launch_url(JS_CLEAR_STORAGE)
            except Exception:
                pass
            mostrar_pantalla_consentimiento()
            
        reiniciar_button = ft.TextButton(
            "Reiniciar 🔄 Práctica",
            on_click=reiniciar_practica,
            style=ft.ButtonStyle(
                color=COLORES["accento"],
                bgcolor=COLORES["error"],
                padding=ft.padding.symmetric(10, 5),
                shape=ft.RoundedRectangleBorder(radius=10),
            )
        )
        
        # Layout principal con el botón de reinicio en la esquina
        header_row = ft.Column([
            ft.Row([titulo_label, reiniciar_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            barra_progreso
        ], spacing=10)

        page.clean()
        
        page.add(
            ft.Column(
                [header_row, temporizador_text, main_row],
                spacing=20,
                expand=True,
                alignment=ft.MainAxisAlignment.START,  # 👈 prevents vertical centering
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        
        # start
        cargar_problema(problema_actual_id)
        
        # Temporizador (Xmin)
        def iniciar_temporizador():
            start_epoch = load_k(page, STATE_KEYS["timer_start"], None)
            now = int(time.time())
            if start_epoch is None:
                start_epoch = now
                save_k(page, STATE_KEYS["timer_start"], start_epoch)

            TOTAL_SECONDS = 120 * 60
            elapsed = max(0, now - int(start_epoch))
            remaining = max(0, TOTAL_SECONDS - elapsed)

            def cuenta():
                nonlocal stop_timer
                while getattr(page, "_is_loading_problem", False):
                    time.sleep(0.1)
                t = remaining
                while t > 0 and not stop_timer:
                    m, s = divmod(t, 60)
                    percent = t / TOTAL_SECONDS
                    if percent > 0.5:
                        temporizador_text.color = COLORES["exito"]      # verde
                    elif percent > 0.25:
                        temporizador_text.color = COLORES["advertencia"]  # amarillo
                    else:
                        temporizador_text.color = COLORES["error"]       # rojo
                    temporizador_text.value = f"{m:02}:{s:02}"
                    page.update()
                    time.sleep(1)
                    t -= 1
                if not stop_timer:
                    stop_timer = True
                    temporizador_text.value = "¡Tiempo terminado!"
                    page.update()
                    try:
                        page.call_from_async(lambda: mostrar_pantalla_encuesta_final())
                    except Exception:
                        threading.Timer(0.5, lambda: mostrar_pantalla_encuesta_final()).start()

            if page.session:
                threading.Thread(target=cuenta, daemon=True).start()
            else:
                print("[DEBUG] Flet page not ready — timer thread skipped.")

        iniciar_temporizador()


    # =============== PANTALLA 5: ENCUESTA FINAL ===============
    def mostrar_pantalla_encuesta_final():
        save_k(page, STATE_KEYS["screen"], "final")
        def copiar_codigo_final(e):
            # Retrieve the identification code from persistent storage
            correo_guardado = page.client_storage.get("correo_identificacion") or "No disponible"
            # Copy to clipboard
            page.set_clipboard(correo_guardado)
            # Reuse the same snackbar pattern as the working function
            page.snack_bar = save_snack
            page.snack_bar.content = ft.Text("Correo copiado al portapapeles", color=COLORES["accento"])
            page.snack_bar.bgcolor = COLORES["exito"]
            page.snack_bar.open = True
            # Refresh the UI
            page.update()

        instruccion = ft.Text(
            "Después de terminar los problemas, te agradecería mucho que respondieras la siguiente encuesta, ya que es muy importante conocer tu experiencia con la app. Por favor, copia y pega tu correo en esta última encuesta. Al finalizarla, habrás completado exitosamente tu actividad y podrás cerrar todas las pestañas utilizadas.",
            size=18, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.JUSTIFY,
        )
        codigo_btn = ft.TextButton(
            content=ft.Text(
                page.client_storage.get("correo_identificacion"),
                size=26, weight="bold",
                color=COLORES["texto"], text_align=ft.TextAlign.CENTER
            ),
            on_click=copiar_codigo_final,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(20, 10),
                side=ft.BorderSide(1.5, COLORES["boton"]),
                shape=ft.RoundedRectangleBorder(radius=8),
                bgcolor=COLORES["accento"]
            ),
        )
        link_final = ft.TextButton(
            "Encuesta de Satisfacción",
            url="https://forms.gle/MfcjCF3oNs77zXtp8",
            url_target=ft.UrlTarget.BLANK,
            style=ft.ButtonStyle(
                color=COLORES["accento"],
                bgcolor=COLORES["exito"],
                padding=ft.padding.symmetric(20, 10),
                shape=ft.RoundedRectangleBorder(radius=8)
            ),
        )
        
        layout = ft.Column([instruccion, ft.Divider(10), codigo_btn, ft.Divider(20), link_final, ft.Divider(30)], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15)
        container = ft.Container(content=layout, padding=30, bgcolor=COLORES["accento"], border_radius=10, shadow=ft.BoxShadow(blur_radius=10, color=COLORES["borde"]), width=600)
        
        reiniciar_button_final = ft.TextButton(
            "Reiniciar 🔄 Práctica",
            on_click=lambda e: (reset_progress(page), mostrar_pantalla_consentimiento()),
            style=ft.ButtonStyle(
                color=COLORES["accento"],
                bgcolor=COLORES["error"],
                padding=ft.padding.symmetric(10, 5),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
        )

        page.clean()
        header_row = ft.Row(
            [ft.Container(), reiniciar_button_final],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        page.add(
            ft.Column(
                [header_row, container],
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            )
        )

    # Boot
    screen = load_k(page, STATE_KEYS["screen"], "consent")
    if screen in ("instructions", "survey"):
        mostrar_pantalla_seleccion_sesion()
    elif screen == "problems":
        titulo = load_k(page, "selected_session_title", "Sesión")
        problemas = load_k(page, "selected_session_problems", [])
        if problemas:
            mostrar_pantalla_intervencion(titulo, problemas)
        else:
            mostrar_pantalla_seleccion_sesion()
    elif screen == "final":
        mostrar_pantalla_encuesta_final()
    else:
        mostrar_pantalla_consentimiento()


if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"  # 👈 forces web mode instead of desktop
    port = int(os.getenv("PORT", "3000"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
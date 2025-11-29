import flet as ft
import requests, time, threading, os, json

# Paleta CLARA
LIGHT_COLORS = {
    "fondo": "#F5F7FA",
    "accento": "#E8F1FA",
    "texto": "#1E2A38",
    "subtitulo": "#4E5D6C",
    "primario": "#1A4E8A",
    "secundario": "#5BA3D0",
    "boton": "#1A4E8A",
    "borde": "#C8D6E5",
    "exito": "#2E8B57",
    "error": "#D64541",
    "advertencia": "#E0A800",
}

# Paleta OSCURA
DARK_COLORS = {
    "fondo":     "#0B0F14",
    "accento":   "#161A20",
    "texto":     "#E6E9EF",
    "subtitulo": "#AAB3C0",
    "primario":  "#8FB7FF",
    "secundario":"#5B96F7",
    "boton":     "#1F3B86",
    "borde":     "#2B323A",
    "exito":     "#2ECC95",
    "error":     "#F2797B",
    "advertencia":"#F6A721",
}

EXERCISES_PATH          = "exercises"
BASE                    = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_CHAT        = f"{BASE}/chat"
BACKEND_URL_VERIFICAR   = f"{BASE}/verificar_respuesta"

# ---- Persistence helpers (top of file) ----
STATE_KEYS = {
    "screen": "ui_screen",                     # "consent", "instructions", "survey", "problems", "final"
    "code": "correo_identificacion",           # unique identification code of the user
    "current_problem": "current_problem_id",   # which problem is being worked on
    "answers": "answers_map",                  # dict: {problem_id: "answer text"}
    "chat": "chat_map",                        # dict: {problem_id: [{"role":"user|agent","text":"..."}]}
    "timer_start": "timer_start_epoch",        # int epoch seconds when Xmin started
    "pending_queue": "pending_queue_list",     # list: [{"type": "chat|answer", "data": {...}}]
}

def listar_sesiones():
    try:
        return [f for f in os.listdir(EXERCISES_PATH) if f.endswith(".json")]
    except FileNotFoundError:
        return []
        
def cargar_sesion(nombre_archivo):
    try:
        with open(os.path.join(EXERCISES_PATH, nombre_archivo), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("title", nombre_archivo), data.get("problemas", [])
    except Exception as e:
        print(f"⚠️ Error al cargar sesión {nombre_archivo}: {e}")
        return nombre_archivo, []
        
def save_k(page, k, v):
    page.client_storage.set(k, v)
    try:
        page.client_storage.set("last_heartbeat", time.time())
    except Exception:
        pass
    
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
        m[pid] = item
    elif key == STATE_KEYS["chat"]:
        m.setdefault(pid, []).append(item)
    save_k(page, key, m)
    
def reset_progress(page):
    try:
        keys = page.client_storage.get_keys("")
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
        
def add_to_pending_queue(page, item: dict):
    if "retry_count" not in item:
        item["retry_count"] = 0
    queue = load_k(page, STATE_KEYS["pending_queue"], []) or []
    queue.append(item)
    save_k(page, STATE_KEYS["pending_queue"], queue)
    
def main(page: ft.Page):
    page.is_alive = True
    
    try:
        last_heartbeat = page.client_storage.get("last_heartbeat")
        now = time.time()
        should_reset = False
        if last_heartbeat and (now - last_heartbeat > 3600):
            print(f"🕒 Sesión expirada por inactividad ({int(now - last_heartbeat)}s). Reseteando...")
            reset_progress(page)
            page.client_storage.set("last_heartbeat", now)
    except Exception as e:
        print(f"⚠️ Error verificando sesión: {e}")
        
    def on_disconnect_handler(e):
        page.is_alive = False
        print("El usuario se desconectó, deteniendo hilos...")
        
    page.on_disconnect = on_disconnect_handler
    theme_name = load_k(page, "theme", "dark")  # "dark" o "light"
    COLORES = DARK_COLORS.copy() if theme_name == "dark" else LIGHT_COLORS.copy()
    page.title = "Grow Together"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START  # 👈 pin everything to the top
    page.scroll = ft.ScrollMode.ALWAYS
    page.padding = 20
    page.bgcolor = COLORES["fondo"]
    page.theme_mode = ft.ThemeMode.DARK if theme_name == "dark" else ft.ThemeMode.LIGHT
    
    page.theme = ft.Theme(
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color={"default": COLORES["primario"]},
            track_color={"default": COLORES["borde"]},
            thickness=10,
            radius=10,
        )
    )
    
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
        
    def _apply_theme_and_redraw():
        nonlocal theme_name, COLORES
        theme_name = load_k(page, "theme", "dark")
        COLORES = DARK_COLORS.copy() if theme_name == "dark" else LIGHT_COLORS.copy()
        page.bgcolor = COLORES["fondo"]
        page.theme_mode = ft.ThemeMode.DARK if theme_name == "dark" else ft.ThemeMode.LIGHT
        _render_current_screen()

    def _render_current_screen():
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
            
    def toggle_theme(e=None):
        new_theme = "light" if load_k(page, "theme", "dark") == "dark" else "dark"
        save_k(page, "theme", new_theme)
        _apply_theme_and_redraw()

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
            overlay_color=COLORES["error"],
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
            with open(os.path.join(EXERCISES_PATH, nombre_archivo), "r", encoding="utf-8") as f:
                data = json.load(f)
            save_k(page, "selected_session_meta", data)
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
        
    def reiniciar_practica(e):
        try:
            reset_progress(page)
            page.launch_url("/", web_window_name="_self")
        except Exception as ex:
            print(f"[WARN] Reinicio fallido: {ex}")
            mostrar_pantalla_consentimiento()
            
    # =============== PANTALLA 3: INTERVENCIÓN (CHAT + PROBLEMAS) ===============
    def mostrar_pantalla_intervencion(titulo_sesion, PROBLEMAS):
        save_k(page, STATE_KEYS["screen"], "problems")
        user_input = None
        correo = page.client_storage.get("correo_identificacion") or "No disponible"
        stop_timer = False
        page.input_is_focused = False
        def on_input_focus(e): page.input_is_focused = True
        def on_input_blur(e): page.input_is_focused = False
        def on_global_keyboard(e):
            if e.key and len(e.key) == 1 and not page.input_is_focused: user_input.focus()
        page.on_keyboard_event = on_global_keyboard
        problema_actual_id = 1
        NUM_PROBLEMAS = len(PROBLEMAS)
        timer_hidden = False
        last_timer_string = ""
        last_timer_color = COLORES["primario"]
        is_retransmiting = False
        prev = load_k(page, "respuestas_enviadas", [])
        if not isinstance(prev, list) or len(prev) != NUM_PROBLEMAS: respuestas_enviadas = [False] * NUM_PROBLEMAS
        else: respuestas_enviadas = prev
        save_k(page, "respuestas_enviadas", respuestas_enviadas)
        debounce_timers = {}
        DEBOUNCE_DELAY_SECONDS = 1.0
        
        def debounce_save(id_problema: int, value: str):
            pid = str(id_problema)
            if pid in debounce_timers and debounce_timers[pid] is not None:
                debounce_timers[pid].cancel()
            def perform_save():
                try:
                    save_k(page, f"respuesta_{id_problema}", value)
                except Exception as _:
                    pass
            t = threading.Timer(DEBOUNCE_DELAY_SECONDS, perform_save)
            debounce_timers[pid] = t
            t.start()
            
        def construir_barra_progreso():
            progress_squares = []
            for i in range(1, NUM_PROBLEMAS + 1):
                color = COLORES["primario"] if i == problema_actual_id else (COLORES["exito"] if respuestas_enviadas[i - 1] else COLORES["advertencia"])
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
            if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                texto = (respuesta_container.controls[0].value or "").strip()
                save_k(page, f"respuesta_{problema_actual_id}", texto)
                
        def add_chat_bubble(role, text):
            is_user = role == "user"
            chat_area.controls.append(
                ft.Container(
                    content=ft.Text(
                        text,
                        color=COLORES["primario"] if is_user else COLORES["texto"],
                        size=16,
                        selectable=True
                    ),
                    padding=ft.padding.symmetric(horizontal=10, vertical=10),
                    alignment=ft.alignment.center_right if is_user else ft.alignment.center_left,
                    border_radius=ft.border_radius.all(10),
                    width=float("inf"),
                )
            )
            chat_area.auto_scroll = True
            chat_area.update()
            chat_area.auto_scroll = False
            
        def cargar_chat_guardado(id_problema):
            #Recupera el historial del chat de un problema.
            chat_area.controls.clear()
            chats = load_k(page, STATE_KEYS["chat"], {})
            for msg in chats.get(str(id_problema), []):
                add_chat_bubble(msg["role"], msg["text"])
            chat_area.auto_scroll = True
            chat_area.update()
            chat_area.auto_scroll = False

        # 🔹 Restore last open problem
        saved_id = load_k(page, STATE_KEYS["current_problem"], 1)
        problema_actual_id = int(saved_id)

        # ---- Funciones internas ----
        def cargar_problema(id_problema: int):
            nonlocal problema_actual_id
            if user_input is not None: save_k(page, f"chat_draft_{problema_actual_id}", user_input.value)
            problema_actual_id = id_problema
            save_k(page, STATE_KEYS["current_problem"], problema_actual_id)
            chat_area.controls.clear()
            siguiente_button.disabled = False
            enviar_button.disabled = False
            retroceder_button.disabled = False
            page.update()
            if getattr(page, "_is_loading_problem", False): return
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
                    hint_text="Escribe tu respuesta aquí, presionando «Enter» para realizar salto de línea",
                    expand=True, multiline=True, min_lines=1, max_lines=10,
                    bgcolor=COLORES["secundario"],
                    border_color=COLORES["secundario"],
                    focused_border_color=COLORES["exito"],
                    border_radius=10,
                    hint_style=ft.TextStyle(color=COLORES["subtitulo"]),
                    color=COLORES["accento"],
                    on_change=lambda e, pid=id_problema: debounce_save(pid, e.control.value),
                    on_focus=on_input_focus,
                    on_blur=on_input_blur
                )

                draft = page.client_storage.get(f"respuesta_{id_problema}")
                if draft: tf.value = draft
                respuesta_container.controls.append(tf)
                chat_draft = load_k(page, f"chat_draft_{id_problema}", "")
                if user_input is not None: user_input.value = chat_draft
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
                # Dynamic color for Estado
                if "Pendiente" in estado:
                    estado_text.color = COLORES["advertencia"]
                else:
                    estado_text.color = COLORES["exito"]
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Completados: {entregados} de {NUM_PROBLEMAS}"
                # Dynamic color for Progreso
                progreso_ratio = entregados / NUM_PROBLEMAS if NUM_PROBLEMAS > 0 else 0
                if progreso_ratio < 0.33:
                    progreso_text.color = COLORES["error"]
                elif progreso_ratio < 0.66:
                    progreso_text.color = COLORES["advertencia"]
                else:
                    progreso_text.color = COLORES["exito"]
                    
                barra_progreso.controls.clear()
                barra_progreso.controls.extend(construir_barra_progreso().controls)
                page.update()
        
        def mostrar_aviso(mensaje):
            feedback_text.value = mensaje
            feedback_text.color = COLORES["advertencia"]
            page.update()
            def limpiar():
                if feedback_text.value == mensaje:
                    feedback_text.value = ""
                    page.update()
            threading.Timer(3.0, limpiar).start()
        
        def ir_a_problema(delta):
            nonlocal problema_actual_id
            guardar_respuesta_actual()
            nuevo_id = problema_actual_id + delta

            # ⛔ Si intenta ir antes del primer problema
            if nuevo_id < 1:
                mostrar_aviso("¡Estás en el primer problema!")
                return

            # ⛔ Si intenta ir después del último problema
            if nuevo_id > NUM_PROBLEMAS:
                if all(respuestas_enviadas):
                    stop_timer = True
                    mostrar_pantalla_encuesta_final()
                else:
                    mostrar_aviso("¡Aún tienes problemas pendientes por contestar!")
                return
                
            cargar_problema(nuevo_id)

        # app_chat.py (Reemplazar la función enviar_respuesta dentro de mostrar_pantalla_intervencion)

        def enviar_respuesta(e):
            if getattr(page, "_is_sending_response", False):
                return
            page._is_sending_response = True
            nonlocal problema_actual_id, stop_timer
            enviar_button.disabled = True
            page.update()

            try:
                val = ""
                # 1. Validación de respuesta no vacía (Lógica original - CORRECTA)
                if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                    val = (respuesta_container.controls[0].value or "").strip()
                if not val:
                    mostrar_aviso("¡La respuesta no puede estar vacía!")
                    enviar_button.disabled = False
                    return

                practice_name = load_k(page, "selected_session_filename", "unknown_session.json")
                
                # DATOS DE LA PETICIÓN
                payload = {
                    "respuesta": val,
                    "correo_identificacion": correo,
                    "practice_name": practice_name
                }
                
                is_success = False

                # 2. INTENTO DE ENVÍO y MANEJO de FALLO (AQUÍ ES DONDE FALTABA EL MANEJO DE LA COLA)
                try:
                    resp = requests.post(
                        f"{BACKEND_URL_VERIFICAR}/{problema_actual_id}",
                        json=payload,
                        timeout=5,
                    )
                    resp.raise_for_status()
                    is_success = True
                    
                except requests.exceptions.RequestException as req_ex:
                    # ⚠️ Fallo de conexión o timeout: Agregar a la cola
                    print(f"❌ Falló el envío de respuesta. Agregando a cola. Error: {req_ex}")
                    add_to_pending_queue(page, {
                        "type": "answer",
                        "problema_id": problema_actual_id,
                        "data": payload,
                    })
                    # Muestra un mensaje temporal sin bloquear el avance
                    # Usamos page.run_thread porque estamos en el thread principal, pero es buena práctica de Flet para UI
                    flash("Guardando en segundo plano... puedes continuar :)", ok=True)
                    
                
                # 3. Lógica de GUARDADO LOCAL y AVANCE (Se ejecuta siempre, independientemente del éxito del envío)
                save_k(page, f"respuesta_{problema_actual_id}", val)
                respuestas_enviadas[problema_actual_id - 1] = True
                save_k(page, "respuestas_enviadas", respuestas_enviadas)
                
                # 🔄 Refrescar rótulos de Estado / Progreso
                if is_success:
                    estado_text.value = "Estado: ✅ Entregado"
                    estado_text.color = COLORES["exito"]
                    save_snack.open = True
                else:
                    estado_text.value = "Estado: ⚠️ Pendiente de Envío"
                    estado_text.color = COLORES["error"]
                
                # Esto es copiado de tu lógica original (Progreso - CORRECTO)
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Completados: {entregados} de {NUM_PROBLEMAS}"
                progreso_ratio = entregados / NUM_PROBLEMAS if NUM_PROBLEMAS > 0 else 0
                if progreso_ratio < 0.33:
                    progreso_text.color = COLORES["error"]
                elif progreso_ratio < 0.66:
                    progreso_text.color = COLORES["advertencia"]
                else:
                    progreso_text.color = COLORES["exito"]

                feedback_text.value = "" # Limpiar feedback
                status_icon.visible = True
                status_text.value = "Guardado" if is_success else "Guardado (Pendiente de Envío)"
                status_row.visible = True
                
                # 🔄 Refresh progress bar colors
                barra_progreso.controls.clear()
                barra_progreso.controls.extend(construir_barra_progreso().controls)
                
                # --- Verificar existencia del siguiente problema ---
                next_id = problema_actual_id + 1
                if next_id <= NUM_PROBLEMAS:
                    save_k(page, STATE_KEYS["current_problem"], next_id)
                    cargar_problema(next_id)
                else:
                    feedback_text.value = "¡Este fue el último problema disponible! Presiona «Siguiente» para finalizar si ya entregaste todo"
                    feedback_text.color = COLORES["advertencia"]
                    enviar_button.disabled = False
                
                page.update()
                
                if is_success:
                    # Ocultar el estado "Guardado" después de 1.2s solo si fue exitoso
                    threading.Timer(1.5, lambda: (setattr(status_row, "visible", False), page.update())).start()

            except Exception as e:
                # Caso de fallo inesperado (JSON malformado, etc.) que no es de red.
                print(f"Error inesperado en enviar_respuesta: {e}")
                feedback_text.value = "Error inesperado al registrar o cargar el siguiente problema."
                feedback_text.color = COLORES["error"]
                enviar_button.disabled = False
                page.update()
            finally:
                # Siempre desbloquear
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
            current_pid = problema_actual_id
            msg = (user_input.value or "").strip()
            if not msg:
                chat_area.controls.append(
                    ft.Container(
                        content=ft.Text("Por favor, escribe un mensaje", color=COLORES["error"], size=16),
                        padding=20, bgcolor=ft.colors.RED_50, border_radius=10,
                        alignment=ft.alignment.center,
                    )
                )
                page.update()
                return

            # 1. Mostrar mensaje del usuario inmediatamente
            add_chat_bubble("user", msg)
            user_input.value = ""
            save_k(page, f"chat_draft_{current_pid}", "")
            user_input.focus()
            page.update()
            update_map(page, STATE_KEYS["chat"], current_pid, {"role": "user", "text": msg})

            # Datos para el backend
            payload = {
                "message": msg,
                "correo_identificacion": correo,
                "practice_name": load_k(page, "selected_session_filename", "unknown_session.json")
            }

            # 2. POLLING
            def poll_loop():
                loading_text = "Escribiendo..."
                loading_bubble = ft.Container(
                    content=ft.Text(loading_text, color=COLORES["subtitulo"], italic=True),
                    padding=ft.padding.symmetric(horizontal=10, vertical=10),
                    alignment=ft.alignment.center_left,
                    border_radius=ft.border_radius.all(10),
                )
                if page.is_alive:
                    chat_area.controls.append(loading_bubble)
                    page.update()
                # --- PASO A: Envío Inicial ---
                try:
                    print(f"[DEBUG] Enviando mensaje | Usuario: {correo} | Práctica: {payload['practice_name']} | Problema: {current_pid}")
                    r_init = requests.post(
                        f"{BACKEND_URL_CHAT}/{current_pid}",
                        json=payload,
                        timeout=60 
                    )
                    r_init.raise_for_status()
                except Exception as ex:
                    if page.is_alive and loading_bubble in chat_area.controls:
                        chat_area.controls.remove(loading_bubble)
                    print(f"❌ Error envío inicial: {ex}")
                    add_to_pending_queue(page, {
                        "type": "chat",
                        "problema_id": current_pid,
                        "data": payload,
                    })
                    if page.is_alive:
                        add_chat_bubble("system", "Sin conexión. Se reintentará automáticamente.")
                        page.update()
                    return
                    
                # --- PASO B: Bucle de Espera ---
                max_retries = 80 
                retry_count = 0
                while retry_count < max_retries:
                    if not page.is_alive: return
                    time.sleep(3)
                    try:
                        current_ui_id = int(load_k(page, STATE_KEYS["current_problem"], 1))
                        if current_ui_id != current_pid:
                            return 
                        r = requests.post(
                            f"{BASE}/check_new_messages/{current_pid}",
                            json={"correo_identificacion": correo},
                            timeout=10
                        )
                        r.raise_for_status()
                        data = r.json()
                        status = data.get("status")
                        if status == "error":
                            if page.is_alive:
                                if loading_bubble in chat_area.controls:
                                    chat_area.controls.remove(loading_bubble)
                                add_chat_bubble("system", f"Error del tutor: {data.get('message', 'Desconocido')}")
                                page.update()
                            return

                        if status == "completed":
                            final_response = data.get("response")
                            print(f"[DEBUG] ¡Respuesta recibida! Longitud: {len(final_response)} caracteres.")
                            if page.is_alive:
                                if loading_bubble in chat_area.controls:
                                    chat_area.controls.remove(loading_bubble)
                                add_chat_bubble("assistant", final_response)
                                update_map(page, STATE_KEYS["chat"], current_pid, {"role": "assistant", "text": final_response})
                                page.update()
                            return
                            
                    except Exception as e:
                        print(f"❌ Polling CRASH en intento {retry_count}: {e}")
                        
                    retry_count += 1
                    
                if page.is_alive:
                    if loading_bubble in chat_area.controls:
                        chat_area.controls.remove(loading_bubble)
                    add_chat_bubble("system", "El sistema tardó demasiado. Intenta preguntar de nuevo.")
                    page.update()
                        
            threading.Thread(target=poll_loop, daemon=True).start()
            
        user_input = ft.TextField(
            hint_text="Escribe tu mensaje aqui, presionando «Enter» para enviarlo",
            bgcolor=COLORES["secundario"],
            border_color=COLORES["secundario"],
            focused_border_color=COLORES["exito"],
            border_radius=10,
            hint_style=ft.TextStyle(color=COLORES["subtitulo"]),
            color=COLORES["accento"],
            max_length=1000,
            on_submit=send_message,
            on_focus=on_input_focus,
            on_blur=on_input_blur
        )

        # ---- Problem area ----
        ejercicio_text = ft.Text("Aquí aparecerá el enunciado del problema", size=20, weight="bold", color=COLORES["texto"])
        respuesta_container = ft.Column(spacing=20)
        feedback_text = ft.Text("", size=16, color=COLORES["exito"], text_align=ft.TextAlign.CENTER)
        status_icon = ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=COLORES["exito"], size=18, visible=False)
        status_text = ft.Text("", size=12, color=COLORES["exito"])
        status_row = ft.Row([status_icon, status_text], spacing=10, visible=False)
        
        retroceder_button = ft.ElevatedButton(
            "⏪ Anterior",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=30, vertical=20),
            ),
            on_click=lambda e: ir_a_problema(-1)
        )

        enviar_button = ft.ElevatedButton(
            "Contestar ✅ Pregunta",
            bgcolor=COLORES["exito"],
            color=COLORES["accento"],
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=30, vertical=20),
            ),
            on_click=enviar_respuesta
        )

        siguiente_button = ft.ElevatedButton(
            "Siguiente ⏩",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=30, vertical=20),
            ),
            on_click=lambda e: ir_a_problema(+1)
        )

        botones_row = ft.Row(
            [retroceder_button, enviar_button, siguiente_button],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=30
        )

        numero_text = ft.Text(
            f"Problema: {problema_actual_id} de {NUM_PROBLEMAS}",
            color=COLORES["primario"],
            size=14
        )
        
        estado_text = ft.Text(
            "",
            size=14,
            color=COLORES["advertencia"]
        )
        
        progreso_text = ft.Text(
            "",
            size=14,
            color=COLORES["error"]
        )
        
        titulo_label = ft.Text(
            f"{titulo_sesion}",
            size=20, color=COLORES["primario"], weight="bold",
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
        
        def toggle_timer(e):
            nonlocal timer_hidden, last_timer_string, last_timer_color
            timer_hidden = not timer_hidden
            if timer_hidden:
                # Show placeholder label but DO NOT stop timer thread
                temporizador_text.value = "Tiempo"
                temporizador_text.color = last_timer_color
            else:
                # Restore the most recent computed value and color
                temporizador_text.value = last_timer_string or temporizador_text.value
                temporizador_text.color = last_timer_color
            page.update()
 
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
            
        reiniciar_button = ft.ElevatedButton(
            "Reiniciar 🔄 Práctica",
            bgcolor=COLORES["error"],
            color=COLORES["accento"],
            on_click=reiniciar_practica,
        )
        
        theme_icon_btn = ft.IconButton(
            icon = ft.Icons.LIGHT_MODE if theme_name == "dark" else ft.Icons.DARK_MODE,
            tooltip = "Cambiar tema",
            icon_color = COLORES["primario"],
            on_click = toggle_theme,
        )
        
        # Layout principal con el botón de reinicio en la esquina
        header_row = ft.Row(
            [
                ft.Row([theme_icon_btn, titulo_label], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(barra_progreso, expand=True, alignment=ft.alignment.center),
                ft.GestureDetector(
                    content=ft.Container(
                        temporizador_text,
                        alignment=ft.alignment.center,
                        padding=ft.padding.symmetric(horizontal=12),
                    ),
                    on_tap=toggle_timer,
                ),
                reiniciar_button,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        page.clean()
        
        page.add(
            ft.Column(
                [header_row, main_row],
                spacing=20,
                expand=True,
                alignment=ft.MainAxisAlignment.START,
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

            # 🔹 Leer tiempo máximo de la práctica o de un problema
            session_data = load_k(page, "selected_session_problems", [])
            session_meta = load_k(page, "selected_session_meta", {}) or {}

            # Por defecto, 10 minutos (600 s)
            TOTAL_SECONDS = session_meta.get("max_time", 600)

            # O si lo defines por problema:
            current_problem = next((p for p in PROBLEMAS if p.get("id") == problema_actual_id), {})
            TOTAL_SECONDS = current_problem.get("max_time", TOTAL_SECONDS)

            elapsed = max(0, now - int(start_epoch))
            remaining = max(0, TOTAL_SECONDS - elapsed)
            m, s = divmod(remaining, 60)            # mejor usar remaining para reanudar correctamente
            temporizador_text.value = f"{m:02}:{s:02}"
            temporizador_text.color = COLORES["exito"]
            page.update()

            def cuenta():
                nonlocal timer_hidden, last_timer_string, last_timer_color, stop_timer
                while getattr(page, "_is_loading_problem", False):
                    time.sleep(0.1)
                    if not page.is_alive: return
                t = remaining
                while t > 0 and not stop_timer:
                    if not page.is_alive: return
                    m, s = divmod(t, 60)
                    percent = t / TOTAL_SECONDS
                    next_color = COLORES["exito"] if percent > 0.5 else (COLORES["advertencia"] if percent > 0.25 else COLORES["error"])
                    next_value = f"{m:02}:{s:02}"
                    last_timer_color = next_color
                    last_timer_string = next_value
                    if timer_hidden:
                        temporizador_text.color = next_color
                    else:
                        temporizador_text.color = next_color
                        temporizador_text.value = next_value
                    try:
                        page.update()
                    except Exception:
                        return 
                    time.sleep(1)
                    t -= 1
                if not stop_timer:
                    if not page.is_alive: return
                    stop_timer = True
                    finish_text = "¡Tiempo terminado!"
                    last_timer_string = finish_text
                    last_timer_color = COLORES["error"]
                    if not timer_hidden:
                        temporizador_text.value = finish_text
                        temporizador_text.color = COLORES["error"]
                        try:
                            page.update()
                        except Exception:
                            return
                    if page.is_alive:
                        mostrar_pantalla_encuesta_final()
            threading.Thread(target=cuenta, daemon=True).start()
        
        iniciar_temporizador()
        
        def process_pending_queue():
            nonlocal is_retransmiting
            while not stop_timer:
                time.sleep(15) # 15 segundos entre reintentos
                if not page.is_alive: return
                if is_retransmiting: continue
                is_retransmiting = True
                
                queue: list = load_k(page, STATE_KEYS["pending_queue"], []) or []
                new_queue = []
                
                if queue:
                    flash(f"Reintentando {len(queue)} petición(es) pendiente(s)...", ok=True, ms=2000)
                    
                for item in queue:
                    payload = item["data"]
                    problema_id = item["problema_id"]
                    is_success = False
                    MAX_RETRIES = 50
                    
                    try:
                        if item["type"] == "answer":
                            resp = requests.post(f"{BACKEND_URL_VERIFICAR}/{problema_id}", json=payload, timeout=60)
                            resp.raise_for_status()
                            is_success = True
                        elif item["type"] == "chat":
                            resp = requests.post(f"{BACKEND_URL_CHAT}/{problema_id}", json=payload, timeout=60)
                            resp.raise_for_status()
                            is_success = True
                            
                    except requests.exceptions.HTTPError as http_err:
                        item["retry_count"] = item.get("retry_count", 0) + 1 
                        if item["retry_count"] < MAX_RETRIES:
                            new_queue.append(item)
                            print(f"⚠️ Reintento HTTP fallido {item['retry_count']}/{MAX_RETRIES} para {item['type']} {problema_id}. Error: {http_err}")
                        else:
                            flash(f"❌ Descartando {item['type']} para problema {problema_id}. Falló {MAX_RETRIES} veces por error HTTP.", ok=False)
                            print(f"❌ Descartando {item['type']} {problema_id}. Límite de reintentos ({MAX_RETRIES}) alcanzado.")
                            
                    except requests.exceptions.RequestException as e:
                        new_queue.append(item)
                        
                    except Exception as e:
                        print(f"⚠️ Error fatal en reintento de {item['type']}: {e}. Descartando permanentemente.")
                        
                current_queue_on_disk = load_k(page, STATE_KEYS["pending_queue"], []) or []
                items_added_during_process = current_queue_on_disk[len(queue):]
                final_queue = new_queue + items_added_during_process
                if len(final_queue) < len(current_queue_on_disk):
                     save_k(page, STATE_KEYS["pending_queue"], final_queue)
                     if not final_queue:
                         flash("✅ Todas las peticiones pendientes han sido enviadas.", ok=True, ms=2000)
                     else:
                         flash(f"Se enviaron peticiones. Quedan {len(final_queue)} pendientes.", ok=True, ms=2000)
                is_retransmiting = False
                
        threading.Thread(target=process_pending_queue, daemon=True).start()

    # =============== PANTALLA 5: ENCUESTA FINAL ===============
    def mostrar_pantalla_encuesta_final():
        save_k(page, STATE_KEYS["screen"], "final")
        finish_epoch = load_k(page, "finish_epoch")
        if not finish_epoch:
            finish_epoch = int(time.time())
            save_k(page, "finish_epoch", finish_epoch)
        remaining = 600 - (int(time.time()) - finish_epoch)
        if remaining <= 0:
            reiniciar_practica(None)
            return
        def auto_restart_thread():
            time.sleep(remaining)
            if page.is_alive and load_k(page, STATE_KEYS["screen"]) == "final":
                reiniciar_practica(None)
        threading.Thread(target=auto_restart_thread, daemon=True).start()
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
            url="https://forms.gle/HiByXT1jHUQhWnzg9",
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
        
        reiniciar_button_final = ft.ElevatedButton(
            "Reiniciar 🔄 Práctica",
            bgcolor=COLORES["error"],
            color=COLORES["accento"],
            on_click=reiniciar_practica,
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

    _apply_theme_and_redraw()

if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"  # 👈 forces web mode instead of desktop
    port = int(os.getenv("PORT", "3000"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
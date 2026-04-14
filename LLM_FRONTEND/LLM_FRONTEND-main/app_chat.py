import flet as ft
import requests, time, threading, os, json
import socketio

BASE                    = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_CHAT        = f"{BASE}/chat"
BACKEND_URL_VERIFICAR   = f"{BASE}/verificar_respuesta"

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

# Light Theme
LIGHT_COLORS = {
    "fondo":        "#F5F7FA",
    "accento":      "#E8F1FA",
    "texto":        "#1E2A38",
    "subtitulo":    "#4E5D6C",
    "primario":     "#1A4E8A",
    "secundario":   "#5BA3D0",
    "boton":        "#1A4E8A",
    "borde":        "#C8D6E5",
    "exito":        "#2E8B57",
    "error":        "#D64541",
    "advertencia":  "#E0A800",
}

# Dark Theme
DARK_COLORS = {
    "fondo":        "#0B0F14",
    "accento":      "#161A20",
    "texto":        "#E6E9EF",
    "subtitulo":    "#AAB3C0",
    "primario":     "#8FB7FF",
    "secundario":   "#5B96F7",
    "boton":        "#1F3B86",
    "borde":        "#2B323A",
    "exito":        "#2ECC95",
    "error":        "#F2797B",
    "advertencia":  "#F6A721",
}

# Persistent Helpers
STATE_KEYS = {
    "screen":           "ui_screen",
    "code":             "correo_identificacion",
    "current_problem":  "current_problem_id",
    "answers":          "answers_map",
    "chat":             "chat_map",
    "timer_start":      "timer_start_epoch",
    "pending_queue":    "pending_queue_list",
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
    state = {
        "token": load_k(page, "student_token"),
        "correo": load_k(page, "correo_identificacion"),
        "nombre": load_k(page, "student_name", "Estudiante"),
        "teachers_list": []
    }
    
    page.is_alive = True
    sio = socketio.Client()
    page.polling_speed = "slow"
    
    def auth_request(method, endpoint, **kwargs):
        if not state["token"]: return None
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {state['token']}"
        kwargs["headers"] = headers
        try:
            url = f"{BASE}{endpoint}"
            if "timeout" not in kwargs: kwargs["timeout"] = 30
            if method == "GET": return requests.get(url, **kwargs)
            if method == "POST": return requests.post(url, **kwargs)
        except Exception as e:
            print(f"Error request: {e}")
            return None
    
    @sio.on('nuevo_mensaje_bot')
    def on_nuevo_mensaje(data):
        # Verificar que el mensaje sea para este alumno y este problema
        if data['correo'] == state["correo_identificacion"] and data['problema_id'] == problema_actual_id:
            # Apagar el indicador de escritura ("El tutor está escribiendo...")
            hide_typing_indicator()
            
            # Agregar el mensaje a la interfaz
            add_message(data['content'], "assistant")
            page.update()

    # Conectar al servidor al cargar la página
    try:
        sio.connect(BASE)
    except Exception as e:
        print("Error conectando sockets en el chat:", e)
        
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
    page.vertical_alignment = ft.MainAxisAlignment.START 
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
        content=ft.Text("Respuesta guardada",
        color=COLORES["accento"]),
        bgcolor=COLORES["exito"],
        open=False,
        behavior=ft.SnackBarBehavior.FLOATING,
        duration=1000,
        width=400,
        shape=ft.RoundedRectangleBorder(radius=10),
        show_close_icon=False,
    )
    
    def flash(msg: str, ok: bool = False, ms: int = 2000):
        save_snack.content = ft.Container(
            content=ft.Text(
                msg, 
                color=COLORES["accento"], 
                size=18, 
                weight="bold", 
                text_align=ft.TextAlign.CENTER
            ),
            alignment=ft.alignment.center
        )
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
        if not state.get("token"):
            show_login_register()
            return
            
        screen = load_k(page, STATE_KEYS["screen"], "dashboard")
        
        if screen == "dashboard":
            show_student_dashboard()
        elif screen == "consent":
            mostrar_pantalla_consentimiento()
        elif screen == "problems":
            titulo = load_k(page, "selected_session_title", "Sesión")
            problemas = load_k(page, "selected_session_problems", [])
            if problemas:
                mostrar_pantalla_intervencion(titulo, problemas)
            else:
                show_student_dashboard()
        elif screen == "final":
            mostrar_pantalla_encuesta_final()
        else:
            show_student_dashboard()
            
    def toggle_theme(e=None):
        new_theme = "light" if load_k(page, "theme", "dark") == "dark" else "dark"
        save_k(page, "theme", new_theme)
        _apply_theme_and_redraw()

    page.overlay.append(save_snack)
    
    # =============== PANTALLA 1: LOGIN Y REGISTRO =============== 
    def show_login_register(is_register=False):
        save_k(page, STATE_KEYS["screen"], "login")
        page.scroll = False
        page.padding = 0
        page.clean()
        
        email_field = ft.TextField(label="Correo Institucional", width=300, bgcolor=COLORES["accento"], border_color=COLORES["primario"], color=COLORES["texto"], border_radius=10)
        pass_field = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, width=300, bgcolor=COLORES["accento"], border_color=COLORES["primario"], color=COLORES["texto"], border_radius=10)
        name_field = ft.TextField(label="Nombre Completo", width=300, bgcolor=COLORES["accento"], border_color=COLORES["primario"], color=COLORES["texto"], border_radius=10, visible=is_register)
        
        teacher_dropdown = ft.Dropdown(
            label="Selecciona a tu Profesor", width=300,
            bgcolor=COLORES["accento"], border_color=COLORES["primario"], color=COLORES["texto"], border_radius=10,
            visible=is_register
        )

        if is_register:
            try:
                res = requests.get(f"{BASE}/api/public/teachers", timeout=10)
                if res.status_code == 200:
                    state["teachers_list"] = res.json()
                    teacher_dropdown.options = [ft.dropdown.Option(key=str(t["id"]), text=f"{t['nombre']} ({t['email']})") for t in state["teachers_list"]]
            except Exception as e:
                print("Error cargando profesores:", e)

        def submit_action(e):
            if is_register:
                if not email_field.value or not pass_field.value or not name_field.value or not teacher_dropdown.value:
                    flash("Por favor, llena todos los campos", ok=False)
                    return
                try:
                    res = requests.post(f"{BASE}/api/student/register", json={
                        "email": email_field.value,
                        "password": pass_field.value,
                        "nombre": name_field.value,
                        "teacher_ids": [int(teacher_dropdown.value)]
                    }, timeout=10)
                    if res.status_code == 201:
                        flash("Registro exitoso. Iniciando sesión...", ok=True)
                        # Auto-login after registration
                        login_action(email_field.value, pass_field.value)
                    else:
                        flash(res.json().get("msg", "Error al registrar"), ok=False)
                except Exception:
                    flash("Error de conexión", ok=False)
            else:
                login_action(email_field.value, pass_field.value)

        def login_action(email, password):
            if not email or not password:
                flash("Ingresa correo y contraseña", ok=False)
                return
            try:
                res = requests.post(f"{BASE}/api/student/login", json={"email": email, "password": password}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    state["token"] = data.get("access_token")
                    state["correo"] = data.get("correo")
                    state["nombre"] = data.get("nombre")
                    page.client_storage.set("student_token", state["token"])
                    page.client_storage.set("correo_identificacion", state["correo"])
                    page.client_storage.set("student_name", state["nombre"])
                    flash(f"Bienvenido, {state['nombre']}", ok=True)
                    show_student_dashboard()
                else:
                    flash("Credenciales inválidas", ok=False)
            except Exception:
                flash("Error de conexión", ok=False)

        card = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.ACCOUNT_CIRCLE, size=50, color=COLORES["primario"]),
                ft.Text("Registro de Alumno" if is_register else "Acceso a Estudiantes", size=24, weight="bold", color=COLORES["texto"]),
                ft.Divider(height=10, color="transparent"),
                name_field,
                email_field,
                pass_field,
                teacher_dropdown,
                ft.Divider(height=10, color="transparent"),
                ft.Column([
                    ft.ElevatedButton("Registrarse" if is_register else "Entrar", on_click=submit_action, bgcolor=COLORES["boton"], color=COLORES["texto"], width=300, height=45),
                    ft.TextButton(
                        "¿Ya tienes cuenta? Inicia Sesión" if is_register else "¿No tienes cuenta? Regístrate",
                        on_click=lambda e: show_login_register(not is_register),
                        style=ft.ButtonStyle(color=COLORES["primario"])
                    )
                ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
            bgcolor=COLORES["fondo"], padding=40, border_radius=15, border=ft.border.all(1, COLORES["borde"]),
            shadow=ft.BoxShadow(blur_radius=20, color=COLORES["accento"], offset=ft.Offset(0, 10)),
            width=400, height=650 if is_register else 500
        )
        
        background_image = ft.Image(
            src="/fondo_login.jpg",
            fit=ft.ImageFit.COVER,
            opacity=1.0,
            gapless_playback=True,
        )
        
        layout_login = ft.Stack(
            controls=[
                ft.Container(content=background_image, left=0, top=0, right=0, bottom=0),
                ft.Container(content=card, alignment=ft.alignment.center, left=0, top=0, right=0, bottom=0)
            ], expand=True
        )
        page.add(layout_login)
    
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
            on_click=lambda e: mostrar_pantalla_intervencion(
                load_k(page, "selected_session_title"), 
                load_k(page, "selected_session_problems")
            )
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
            col={"xs": 12, "sm": 10, "md": 8, "lg": 6, "xl": 5}, # Acts as max-width
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            shadow=ft.BoxShadow(blur_radius=10, color=COLORES["borde"]),
        )
        
        final_view = ft.ResponsiveRow(
            [container], 
            alignment=ft.MainAxisAlignment.CENTER
        )
        
        page.clean()
        page.add(final_view)
        
    # =============== PANTALLA 2: DASHBOARD DEL ESTUDIANTE =============== 
    def show_student_dashboard():
        save_k(page, STATE_KEYS["screen"], "dashboard")
        page.clean()
        
        exercises_grid = ft.GridView(expand=True, runs_count=3, max_extent=350, child_aspect_ratio=1.2, spacing=20, run_spacing=20)
        
        def iniciar_practica(filename, title):
            # Fetch the actual problem data securely from the backend instead of local files
            try:
                res = auth_request("GET", f"/api/exercises/detail/{filename}")
                if res and res.status_code == 200:
                    data = res.json()
                    problemas = data.get("problemas", [])
                    
                    save_k(page, "selected_session_meta", data)
                    save_k(page, "selected_session_title", title)
                    save_k(page, "selected_session_problems", problemas)
                    save_k(page, "selected_session_filename", filename)
                    
                    # Proceed to the Consent Screen before starting the problems
                    mostrar_pantalla_consentimiento()
                else:
                    flash("Error al descargar la práctica del servidor.", ok=False)
            except Exception as e:
                print("Error loading practice:", e)
                flash("Error de conexión.", ok=False)

        def load_active_exercises():
            exercises_grid.controls.clear()
            exercises_grid.controls.append(ft.ProgressRing(color=COLORES["primario"]))
            page.update()
            
            try:
                res = auth_request("GET", "/api/student/my-active-exercises", timeout=10)
                exercises_grid.controls.clear()
                
                if res and res.status_code == 200:
                    active_exercises = res.json()
                    if not active_exercises:
                        exercises_grid.controls.append(ft.Text("No tienes tareas activas asignadas en este momento.", color=COLORES["subtitulo"], size=16))
                    else:
                        for ex in active_exercises:
                            minutes = ex.get('max_time', 0) // 60
                            title = ex.get('title', 'Sin Título')
                            filename = ex.get('filename')
                            
                            # Card UI for the assignment
                            card = ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.ASSIGNMENT, color=COLORES["primario"], size=30),
                                        ft.Text(title, weight="bold", size=18, color=COLORES["texto"], expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
                                    ], vertical_alignment=ft.CrossAxisAlignment.START),
                                    ft.Divider(color=COLORES["borde"]),
                                    ft.Text(ex.get('description', ''), size=14, color=COLORES["texto"], max_lines=3, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                                    ft.Row([
                                        ft.Icon(ft.Icons.TIMER, size=14, color=COLORES["subtitulo"]),
                                        ft.Text(f"{minutes} min", size=12, color=COLORES["subtitulo"]),
                                        ft.Container(width=10),
                                        ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, size=14, color=COLORES["subtitulo"]),
                                        ft.Text(f"{ex.get('num_problems', 0)} ejercicios", size=12, color=COLORES["subtitulo"]),
                                    ]),
                                    ft.ElevatedButton("Comenzar Práctica", icon=ft.Icons.PLAY_ARROW, bgcolor=COLORES["boton"], color=COLORES["texto"], width=float("inf"), on_click=lambda e, f=filename, t=title: iniciar_practica(f, t))
                                ]),
                                bgcolor=COLORES["accento"], padding=20, border_radius=10, border=ft.border.all(1, COLORES["borde"]),
                                shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"])
                            )
                            exercises_grid.controls.append(card)
                else:
                    exercises_grid.controls.append(ft.Text("Error al cargar tareas.", color=COLORES["error"]))
            except Exception as e:
                print("Dashboard load error:", e)
                exercises_grid.controls.clear()
                exercises_grid.controls.append(ft.Text("Error de conexión.", color=COLORES["error"]))
                
            page.update()

        header = ft.Container(
            content=ft.Row([
                ft.Row([ft.Icon(ft.Icons.SCHOOL, color=COLORES["primario"], size=30), ft.Text(f"Portal de Alumnos - {state['nombre']}", size=24, weight="bold", color=COLORES["texto"])]),
                ft.Row([
                    ft.IconButton(icon=ft.Icons.LIGHT_MODE if theme_name == "dark" else ft.Icons.DARK_MODE, icon_color=COLORES["primario"], on_click=toggle_theme, tooltip="Cambiar Tema"),
                    ft.IconButton(icon=ft.Icons.LOGOUT, icon_color=COLORES["error"], tooltip="Cerrar Sesión", on_click=lambda e: (page.client_storage.remove("student_token"), state.update({"token": None, "correo": None, "nombre": None}), show_login_register()))
                ])
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=20, bgcolor=COLORES["fondo"], border=ft.border.only(bottom=ft.border.BorderSide(1, COLORES["borde"]))
        )

        page.add(ft.Column([header, ft.Container(content=exercises_grid, padding=30, expand=True)], expand=True))
        
        # Load the assignments dynamically
        threading.Thread(target=load_active_exercises, daemon=True).start()
        
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
                if not getattr(page, 'is_alive', False): return
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
            return ft.Row(
                controls=progress_squares,
                wrap=True,
                spacing=5,
                run_spacing=5,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            
        barra_progreso = construir_barra_progreso()
        
        def guardar_respuesta_actual():
            if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                texto = (respuesta_container.controls[0].value or "").strip()
                save_k(page, f"respuesta_{problema_actual_id}", texto)
                
        def add_chat_bubble(role, text):
            is_user = role == "user"
            is_teacher = role == "teacher"
            
            if is_user:
                txt_color = COLORES["primario"]
                align = ft.alignment.center_right
                bg_color = None
            elif is_teacher:
                txt_color = "#FFFFFF"
                align = ft.alignment.center_left
                bg_color = "#7C3AED"
            else:
                txt_color = COLORES["texto"]
                align = ft.alignment.center_left
                bg_color = None

            bubble_container = ft.Container(
                content=ft.Column([
                    ft.Text("Profesor dice:" if is_teacher else "", size=10, color="white", weight="bold") if is_teacher else ft.Container(),
                    ft.Text(text, color=txt_color, size=16, selectable=True)
                ]),
                padding=ft.padding.symmetric(horizontal=10, vertical=10),
                alignment=align,
                bgcolor=bg_color,
                border_radius=ft.border_radius.all(10),
                width=float("inf"),
            )
            
            chat_area.controls.append(bubble_container)
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
                temp_respuestas = list(respuestas_enviadas)
                temp_respuestas[problema_actual_id - 1] = True
                entregados_pred = sum(1 for x in temp_respuestas if x)
                prog_pred = entregados_pred / NUM_PROBLEMAS if NUM_PROBLEMAS > 0 else 0
                
                # DATOS DE LA PETICIÓN
                payload = {
                    "respuesta": val,
                    "correo_identificacion": correo,
                    "practice_name": practice_name,
                    "progress_pct": prog_pred
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
                    flash("Respuesta guardada", ok=True)
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
            height=None,
            auto_scroll=True,
        )

        chat_container = ft.Container(
            content=chat_area,
            height=400, 
            width=None,
            expand=False,
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        def send_message(e):
            msg = (user_input.value or "").strip()
            if not msg: return

            add_chat_bubble("user", msg)
            user_input.value = ""
            save_k(page, f"chat_draft_{problema_actual_id}", "")
            user_input.focus()
            
            update_map(page, STATE_KEYS["chat"], problema_actual_id, {"role": "user", "text": msg})
            
            page.polling_speed = "fast"
            
            page.burbuja_carga = ft.Container(
                content=ft.Text("Escribiendo...", color=COLORES["subtitulo"], italic=True),
                padding=ft.padding.symmetric(horizontal=10, vertical=10),
                alignment=ft.alignment.center_left,
                border_radius=ft.border_radius.all(10),
            )
            chat_area.controls.append(page.burbuja_carga)
            chat_area.update()
            entregados = sum(1 for x in respuestas_enviadas if x)
            prog_act = entregados / NUM_PROBLEMAS if NUM_PROBLEMAS > 0 else 0

            payload = {
                "message": msg,
                "correo_identificacion": correo,
                "practice_name": load_k(page, "selected_session_filename", "unknown.json"),
                "progress_pct": prog_act
            }

            def send_request_thread():
                try:
                    requests.post(f"{BACKEND_URL_CHAT}/{problema_actual_id}", json=payload, timeout=60)
                except Exception as ex:
                    print(f"❌ Error al enviar mensaje: {ex}")
                    add_to_pending_queue(page, {
                        "type": "chat",
                        "problema_id": problema_actual_id,
                        "data": payload
                    })
                    page.polling_speed = "slow"
                    
                    if getattr(page, "burbuja_carga", None) in chat_area.controls:
                        chat_area.controls.remove(page.burbuja_carga)
                        
                    if page.is_alive:
                        flash("Sin conexión. Se guardó en la cola.", ok=False)
                        
                    chat_area.update()
            
            threading.Thread(target=send_request_thread, daemon=True).start()
            
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
            spacing=30,
            wrap=True,
            run_spacing=10,
        )
        
        botones_container = ft.Container(
            content=botones_row,
            alignment=ft.alignment.center
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
                botones_container,
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
 
        left_panel = ft.Column(
            [chat_container, user_input], 
            col={"sm": 12, "md": 6, "xl": 6},
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        right_panel = ft.Container(
            content=problemas_area,
            padding=20,
            col={"sm": 12, "md": 6, "xl": 6},
            bgcolor=COLORES["accento"],
            border_radius=10,
        )

        main_layout = ft.ResponsiveRow(
            [left_panel, right_panel],
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START
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
        header_group_1 = ft.Container(
            content=ft.Row([theme_icon_btn, titulo_label], spacing=8),
            col={"xs": 12, "md": 4}, # Full width on mobile, 1/3 on PC
            alignment=ft.alignment.center_left,
        )

        # Group 2: Progress Bar (Center)
        header_group_2 = ft.Container(
            content=barra_progreso,
            col={"xs": 12, "md": 4}, # Full width on mobile, 1/3 on PC
            alignment=ft.alignment.center,
        )

        # Group 3: Timer & Restart (Right)
        header_group_3 = ft.Container(
            content=ft.Row(
                [
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
                spacing=10, 
                alignment=ft.MainAxisAlignment.END # Internal alignment
            ),
            col={"xs": 12, "md": 4}, # Full width on mobile, 1/3 on PC
            alignment=ft.alignment.center_right, # Container alignment
        )

        # The Main Responsive Header
        header_row = ft.ResponsiveRow(
            [header_group_1, header_group_2, header_group_3],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            run_spacing=10,
        )
        
        page.clean()
        
        page.add(
            ft.Column(
                [header_row, main_layout],
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
        
        def background_listener():
            while not stop_timer:
                if not hasattr(page, 'is_alive') or not page.is_alive: 
                    break
                
                sleep_time = 1.5 if page.polling_speed == "fast" else 10.0
                time.sleep(sleep_time)
                
                if not page.is_alive: return
                
                current_p_id = problema_actual_id
                
                try:
                    r = requests.post(
                        f"{BASE}/check_new_messages/{problema_actual_id}",
                        json={"correo_identificacion": correo},
                        timeout=5
                    )
                    
                    if r.status_code == 200:
                        data = r.json()
                        status = data.get("status")
                        
                        if status == "completed":
                            
                            if current_p_id != problema_actual_id:
                                continue
                            texto = data.get("response")
                            rol = data.get("role", "assistant")
                            chat_history = load_k(page, STATE_KEYS["chat"], {})
                            msgs_actuales = chat_history.get(str(problema_actual_id), [])
                            ultimo_local = msgs_actuales[-1]["text"] if msgs_actuales else ""
                            
                            if texto != ultimo_local:
                                if getattr(page, "burbuja_carga", None) in chat_area.controls:
                                    chat_area.controls.remove(page.burbuja_carga)
                                    page.burbuja_carga = None
                                    
                                if rol == "assistant":
                                    page.polling_speed = "slow"
                                    
                                add_chat_bubble(rol, texto)
                                update_map(page, STATE_KEYS["chat"], current_p_id, {"role": rol, "text": texto})
                                
                                if rol == "teacher":
                                    flash("🔔 Nuevo mensaje del profesor", ok=True)
                                page.update()
                                
                except Exception as e:
                    if getattr(page, 'is_alive', False):
                        print(f"[Listener] Ping fallido: {e}")
                        
        threading.Thread(target=background_listener, daemon=True).start()
        
        def process_pending_queue():
            nonlocal is_retransmiting
            while not stop_timer:
                time.sleep(15)
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

    # =============== PANTALLA ENCUESTA FINAL ===============
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
            correo_guardado = page.client_storage.get("correo_identificacion") or "No disponible"
            page.set_clipboard(correo_guardado)
            page.snack_bar = save_snack
            page.snack_bar.content = ft.Text("Correo copiado al portapapeles", color=COLORES["accento"])
            page.snack_bar.bgcolor = COLORES["exito"]
            page.snack_bar.open = True
            page.update()

        instruccion = ft.Text(
            "Después de terminar los problemas, te agradecería mucho que respondieras la siguiente encuesta, ya que es muy importante conocer tu experiencia con la app. Por favor, copia y pega tu correo en esta última encuesta. Al finalizarla, habrás completado exitosamente tu actividad y podrás cerrar todas las pestañas utilizadas.",
            size=18,
            weight="bold",
            color=COLORES["primario"],
            text_align=ft.TextAlign.JUSTIFY,
        )
        
        codigo_btn = ft.TextButton(
            content=ft.Text(
                load_k(page, "correo_identificacion", "No_Disponible"),
                size=26,
                weight="bold",
                color=COLORES["texto"],
                text_align=ft.TextAlign.CENTER,
            ),
            on_click=copiar_codigo_final,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(20, 10),
                side=ft.BorderSide(1.5, COLORES["boton"]),
                shape=ft.RoundedRectangleBorder(radius=10),
                bgcolor=COLORES["accento"],
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
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
        )
        
        layout = ft.Column(
            [
                instruccion, ft.Divider(20),
                codigo_btn, ft.Divider(20),
                link_final, ft.Divider(20),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )
        
        container = ft.Container(
            content=layout,
            col={"xs": 12, "sm": 10, "md": 8, "lg": 6, "xl": 5},
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            shadow=ft.BoxShadow(blur_radius=10, color=COLORES["borde"]),
        )
        
        reiniciar_button_final = ft.ElevatedButton(
            "Reiniciar 🔄 Práctica",
            bgcolor=COLORES["error"],
            color=COLORES["accento"],
            on_click=reiniciar_practica,
        )

        page.clean()
        
        header_row = ft.ResponsiveRow(
            [
                ft.Container(
                    content=reiniciar_button_final,
                    col={"xs": 12},
                    alignment=ft.alignment.center_right,
                )
            ]
        )

        page.add(
            ft.Column(
                [
                    header_row, 
                    ft.ResponsiveRow([container], alignment=ft.MainAxisAlignment.CENTER),
                ],
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
            )
        )
        
    _apply_theme_and_redraw()
    
if __name__ == "__main__":
    print(f"📂 RUTA ASSETS FINAL: {ASSETS_PATH}")
    if os.path.exists(ASSETS_PATH):
        print(f"✅ Archivos en assets: {os.listdir(ASSETS_PATH)}")
    else:
        print(f"❌ ADVERTENCIA: No se encuentra la carpeta en: {ASSETS_PATH}")

    os.environ["FLET_FORCE_WEB"] = "1"
    port = int(os.getenv("PORT", "3000"))
    
    ft.app(
        target=main, 
        view=ft.AppView.WEB_BROWSER, 
        host="0.0.0.0", 
        port=port, 
        assets_dir=ASSETS_PATH  # <--- AQUÍ USAMOS LA VARIABLE CALCULADA
    )
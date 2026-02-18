import flet as ft
import requests, time, threading, os, json
import socketio

BASE = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")

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
    "fondo":       "#F5F7FA",
    "accento":     "#E8F1FA",
    "texto":       "#1E2A38",
    "subtitulo":   "#4E5D6C",
    "primario":    "#1A4E8A",
    "secundario":  "#5BA3D0",
    "boton":       "#1A4E8A",
    "borde":       "#C8D6E5",
    "exito":       "#2E8B57",
    "error":       "#D64541",
    "advertencia": "#E0A800",
}

# Dark Theme
DARK_COLORS = {
    "fondo":       "#0B0F14",
    "accento":     "#161A20",
    "texto":       "#E6E9EF",
    "subtitulo":   "#AAB3C0",
    "primario":    "#8FB7FF",
    "secundario":  "#5B96F7",
    "boton":       "#1F3B86",
    "borde":       "#2B323A",
    "exito":       "#2ECC95",
    "error":       "#F2797B",
    "advertencia": "#F6A721",
}

# Persistent Helpers
STATE_KEYS = {
    "screen":          "ui_screen",
    "code":            "correo_identificacion",
    "current_problem": "current_problem_id",
    "answers":         "answers_map",
    "chat":            "chat_map",
    "timer_start":     "timer_start_epoch",
    "pending_queue":   "pending_queue_list",
}

def main(page: ft.Page):
    
    state = {
        "token": page.client_storage.get("teacher_token"),
        "last_activity": time.time(),
        "students": [],
        "dashboard_data": {},
        "my_exercises": [],
        "all_exercises": [],
    }
    
    def on_disconnect(e):
        page.is_alive = False
        print("Cliente desconectado, deteniendo hilos")
    
    def save_k(page, k, v):
        page.client_storage.set(k, v)
    
    def load_k(page, k, default=None):
        try:
            v = page.client_storage.get(k)
            return v if v is not None else default
        except Exception:
            return default
            
    page.is_alive = True
    page.on_disconnect = on_disconnect
    page.title = "Pro-Tutor - Portal Docente"
    page.padding = 0
    theme_name = load_k(page, "theme", "dark")
    COLORES = DARK_COLORS.copy() if theme_name == "dark" else LIGHT_COLORS.copy()
    page.theme_mode = ft.ThemeMode.DARK if theme_name == "dark" else ft.ThemeMode.LIGHT
    page.bgcolor = COLORES["fondo"]
    stored_activity = page.client_storage.get("last_activity")
    
    if stored_activity:
        state["last_activity"] = stored_activity
    
    save_snack = ft.SnackBar(
        content=ft.Text("Placeholder"),
        bgcolor=COLORES["exito"],
        open=False,
        behavior=ft.SnackBarBehavior.FLOATING,
        duration=1000,
        margin=ft.margin.all(20),
        show_close_icon=False, 
    )
    
    page.overlay.append(save_snack)
    sio = socketio.Client()
    is_session_active = False
    student_cards_state = {}
    dashboard_grid = ft.GridView(expand=True, runs_count=5, max_extent=250, child_aspect_ratio=1.0, spacing=10, run_spacing=10)
    session_status_text = ft.Text("Sesión Inactiva", color=COLORES["subtitulo"])

# --- 2.3 DIALOGO DE DETALLES (Pop-up) ---
    detail_dlg_title = ft.Text(weight="bold", size=20)
    detail_dlg_content = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10)
        
    detail_dlg = ft.AlertDialog(
        title=detail_dlg_title,
        content=ft.Container(content=detail_dlg_content, width=500, height=400, padding=10),
        actions=[ft.TextButton("Cerrar", on_click=lambda e: close_detail_dlg())],
        on_dismiss=lambda e: close_detail_dlg()
    )
    
    page.overlay.append(detail_dlg)

    def close_detail_dlg():
        detail_dlg.open = False
        page.update()

    def show_student_detail(email):
        # Verificar si tenemos datos en memoria para este estudiante
        if email not in student_cards_state or 'latest_data' not in student_cards_state[email]:
            # Si no hay datos en tiempo real, mostrar mensaje genérico
            detail_dlg_title.value = f"Estudiante: {email.split('@')[0]}"
            detail_dlg_content.controls.clear()
            detail_dlg_content.controls.append(ft.Text("No hay actividad reciente registrada en esta sesión en vivo.", italic=True))
            detail_dlg.open = True
            page.update()
            return

        data = student_cards_state[email]['latest_data']
        detail_dlg_title.value = f"Análisis: {email.split('@')[0]}"
        detail_dlg_content.controls.clear()

        if data['type'] == 'chat':
            # Estructura visual para CHAT (Semáforo)
            status_map = {"green": "Productivo", "yellow": "Atascado/Distraído", "red": "Crítico/Inapropiado"}
            status_text = status_map.get(data.get('status'), "Desconocido")
            status_color = {"green": COLORES["exito"], "yellow": COLORES["advertencia"], "red": COLORES["error"]}.get(data.get('status'), COLORES["texto"])

            detail_dlg_content.controls.extend([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Estado Detectado:", size=12, color=COLORES["subtitulo"]),
                            ft.Row([
                                ft.Icon(ft.Icons.FIBER_MANUAL_RECORD, color=status_color),
                                ft.Text(status_text, size=18, weight="bold", color=status_color)
                            ])
                        ]),
                        bgcolor=COLORES["accento"], padding=10, border_radius=10
                    ),
                    ft.Divider(),
                    ft.Text("Último Mensaje del Estudiante:", weight="bold"),
                    ft.Container(
                        content=ft.Text(f"\"{data.get('last_message', 'N/A')}\"", italic=True, size=14),
                        bgcolor=COLORES["fondo"], padding=10, border_radius=5, border=ft.border.all(1, COLORES["borde"])
                    ),
                    ft.Divider(),
                    ft.Row([
                        ft.Text("Intención IA:", weight="bold"),
                        ft.Container(
                            content=ft.Text(data.get('intent', 'N/A'), color=COLORES["texto"], size=12),
                            bgcolor=COLORES["primario"], padding=5, border_radius=5
                        )
                    ]),
                    ft.Text(f"Hora: {data.get('timestamp', '').replace('T', ' ')[:16]}", size=10, color=COLORES["subtitulo"])
            ])
            
        elif data['type'] == 'answer':
                # Estructura visual para RESPUESTA (Grading)
                detail_dlg_content.controls.extend([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ASSIGNMENT_TURNED_IN, color=COLORES["primario"]),
                            ft.Text("Nueva Tarea Entregada", weight="bold", size=16)
                        ]),
                        bgcolor=COLORES["accento"], padding=10, border_radius=10
                    ),
                    ft.Text(f"Práctica: {data.get('practice')} - Ejercicio {data.get('problem_id')}", size=14),
                    ft.Divider(),
                    ft.Text(f"Calificación Preliminar IA: {data.get('score', 0)}/10", size=24, weight="bold", color=COLORES["primario"]),
                    ft.Container(
                        content=ft.Text("⚠️ Esta nota es preliminar. Ve a la pestaña 'Evaluaciones' para confirmarla o editarla.", color=COLORES["texto"]),
                        bgcolor=COLORES["advertencia"], padding=10, border_radius=5
                    )
                ])

        detail_dlg.open = True
        page.update()

    @sio.event
    def connect():
        print("✅ Conectado al servidor de tiempo real")
    
    @sio.event
    def disconnect():
        print("❌ Desconectado del servidor de tiempo real")
    
    @sio.event
    def student_activity(data):
        """Handles real-time updates from backend servers."""
        if not is_session_active: return
    
        email = data.get('student_email')
        status_color = data.get('status', 'green')
        print(f"⚡ Actividad recibida: {email} - {status_color}")
    
        # Update the specific student card visually
        if email in student_cards_state:
            card_data = student_cards_state[email]
            card_control = card_data['control']
            
            # Update the border color and icon based on status
            new_color = {
                "green": COLORES["exito"], 
                "yellow": COLORES["advertencia"], 
                "red": COLORES["error"]
            }.get(status_color, COLORES["borde"])
            
            icon_data = {
                "green": (ft.Icons.CHECK_CIRCLE, COLORES["exito"]),
                "yellow": (ft.Icons.WARNING, COLORES["advertencia"]),
                "red": (ft.Icons.ERROR, COLORES["error"])
            }.get(status_color, (ft.Icons.CIRCLE, COLORES["borde"]))
    
            # Update Card UI elements
            card_control.border = ft.border.all(3, new_color)
            status_icon_control = card_control.content.controls[0].controls[1]
            status_icon_control.name = icon_data[0]
            status_icon_control.color = icon_data[1]
            
            # Save latest data for detailed view click
            card_data['latest_data'] = data
            card_control.update()
            
    def _apply_theme():
        target_colors = DARK_COLORS if theme_name == "dark" else LIGHT_COLORS
        COLORES.clear()
        COLORES.update(target_colors)
        page.theme_mode = ft.ThemeMode.DARK if theme_name == "dark" else ft.ThemeMode.LIGHT
        page.bgcolor = COLORES["fondo"]
        page.update()
        
    def toggle_theme(e=None):
        nonlocal theme_name
        theme_name = "light" if theme_name == "dark" else "dark"
        save_k(page, "theme", theme_name)
        _apply_theme()
        
        if state["token"]:
            show_dashboard()
        else:
            show_login()
            
    def flash(msg: str, ok: bool = False, ms: int = 1000):
        save_snack.content = ft.Container(
            content=ft.Text(
                msg,
                color=COLORES["accento"],
                size=18, 
                weight="bold",
                text_align=ft.TextAlign.CENTER,
            ),
            alignment=ft.alignment.center
        )
        save_snack.bgcolor = COLORES["exito"] if ok else COLORES["error"]
        save_snack.duration = ms
        save_snack.open = True
        page.update()
        
    def check_session():
        last_act = state.get("last_activity", 0)
        now = time.time()
        
        if state["token"] and (now - last_act > 3600):
            print("Sesión expirada (Check Session)")
            state["token"] = None
            page.client_storage.remove("teacher_token")
            show_login()
        else:
            reset_inactivity_timer()
            
    def auth_request(method, endpoint, **kwargs):
        check_session()
        if not state["token"]: return None
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {state['token']}"
        kwargs["headers"] = headers
        try:
            url = f"{BASE}{endpoint}"
            if "timeout" not in kwargs: kwargs["timeout"] = 30
            if method == "GET": return requests.get(url, **kwargs)
            if method == "POST": return requests.post(url, **kwargs)
            if method == "DELETE": return requests.delete(url, **kwargs)
        except Exception as e:
            print(f"Error request: {e}")
            return None
            
    def reset_inactivity_timer():
        now = time.time()
        state["last_activity"] = now
        page.client_storage.set("last_activity", now)
    
    def inactivity_checker():
        while True:
            time.sleep(60)
            if not page.is_alive: break
            
            if state["token"]:
                last_act = state.get("last_activity", 0)
                if time.time() - last_act > 3600:
                    print("Sesión expirada por inactividad.")
                    state["token"] = None
                    try:
                        page.client_storage.remove("teacher_token")
                        page.go("/logout_forced")
                    except Exception as e:
                        print(f"Logout background error: {e}")
    threading.Thread(target=inactivity_checker, daemon=True).start()

    def route_change(e):
        if page.route == "/logout_forced":
            page.client_storage.remove("teacher_token")
            state["token"] = None
            flash("Tu sesión ha expirado por inactividad.", ok=False)
            show_login()
            page.route = "/"
    page.on_route_change = route_change
    
    def show_login():
        page.clean()
        
        # --- 1. Lógica y Controles ---
        email_field = ft.TextField(
            label="Correo Docente", 
            width=300,
            bgcolor=COLORES["accento"], 
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            border_radius=10
        )
        
        pass_field = ft.TextField(
            label="Contraseña", 
            password=True, 
            width=300, 
            can_reveal_password=True,
            bgcolor=COLORES["accento"],
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            border_radius=10,
            on_submit=lambda e: login_action(e)
        )
        
        def login_action(e):
            if not email_field.value or not pass_field.value:
                flash("Por favor, ingresa correo y contraseña para iniciar sesión", ok=False)
                return
                
            try:
                res = requests.post(f"{BASE}/api/teacher/login", json={
                    "email": email_field.value,
                    "password": pass_field.value
                }, timeout=10)
                
                if res.status_code == 200:
                    data = res.json()
                    token = data.get("access_token")
                    state["token"] = token
                    page.client_storage.set("teacher_token", token)
                    reset_inactivity_timer()
                    flash(f"Bienvenido, {data.get('nombre', 'Profesor')}", ok=True)
                    show_dashboard()
                else:
                    try:
                        msg_error = res.json().get("msg", "Credenciales incorrectas")
                    except:
                        msg_error = f"Error del servidor ({res.status_code}) o Credenciales incorrectas"
                    flash(msg_error, ok=False)
                    
            except Exception as ex:
                print(f"Login error: {ex}")
                flash("Error de conexión o servidor", ok=False)

        def register_action(e):
            if not email_field.value or not pass_field.value:
                flash("Por favor, ingresa correo y contraseña para registrar nueva cuenta docente", ok=False)
                return
                
            try:
                res = requests.post(f"{BASE}/api/teacher/register", json={
                    "email": email_field.value,
                    "password": pass_field.value
                }, timeout=10)
                if res.status_code == 201:
                    flash("Cuenta docente creada, puedes iniciar sesión", ok=True)
                else:
                    try:
                        msg_error = res.json().get("msg", "Error al registrar cuenta")
                    except:
                        msg_error = f"Error del servidor ({res.status_code}) o Error al registrar cuenta"
                    flash(msg_error, ok=False)
                    
            except Exception as ex:
                print(f"Register error: {ex}")
                flash("Error de conexión o servidor", ok=False)

        # --- 2. Tarjeta CON TAMAÑO RESTRINGIDO ---
        card = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.SCHOOL, size=50, color=COLORES["primario"]),
                ft.Text("Acceso Docente", size=24, weight="bold", color=COLORES["texto"]),
                ft.Divider(height=20, color="transparent"),
                email_field,
                ft.Divider(height=20, color="transparent"),
                pass_field,
                ft.Divider(height=20, color="transparent"),
                ft.Column([
                    ft.ElevatedButton(
                        "Entrar",
                        on_click=login_action,
                        bgcolor=COLORES["boton"],
                        color=COLORES["texto"],
                        width=300,
                        height=45
                    ),
                    ft.TextButton(
                        "¿No tienes cuenta? Regístrate",
                        on_click=register_action,
                        style=ft.ButtonStyle(color=COLORES["primario"])
                    )
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=5),
            bgcolor=COLORES["fondo"],
            padding=40,
            border_radius=15,
            border=ft.border.all(1, COLORES["borde"]),
            shadow=ft.BoxShadow(
                blur_radius=20,
                color=COLORES["accento"],
                offset=ft.Offset(0, 10)
            ),
            width=400,
            height=600
        )

        # --- 3. IMAGEN CON POSICIONAMIENTO ABSOLUTO ---
        background_image = ft.Image(
            src="/fondo_login.jpg",
            fit=ft.ImageFit.COVER,
            opacity=1.0,
            gapless_playback=True,
        )

        layout_login = ft.Stack(
            controls=[
                ft.Container(
                    content=background_image,
                    left=0,
                    top=0,
                    right=0,
                    bottom=0,
                ),
                ft.Container(
                    content=card,
                    alignment=ft.alignment.center,
                    left=0, top=0, right=0, bottom=0,
                )
            ],
            expand=True
        )

        page.add(layout_login)
    
    def show_dashboard():
        check_session()
        page.clean()

        # =========================================
        # PESTAÑA 1: Gestión de Estudiantes
        # =========================================
        state["exercises"] = []
        state["all_users_global"] = []
        state["filter_my_students"] = ""
        state["sort_my_students"] = "asc"
        state["filter_global_students"] = ""
        state["sort_global_students"] = "asc"
        
        search_my_students = ft.TextField(
            hint_text="Buscar estudiantes inscritos...",
            prefix_icon=ft.Icons.SEARCH,
            height=35,
            text_size=12,
            content_padding=10,
            border_radius=15,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            on_change=lambda e: update_filters("my", e.control.value)
        )
        
        sort_btn_my = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_sort("my")
        )
        
        search_global_students = ft.TextField(
            hint_text="Buscar estudiantes disponibles...",
            prefix_icon=ft.Icons.SEARCH,
            height=35,
            text_size=12,
            content_padding=10,
            border_radius=15,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            on_change=lambda e: update_filters("global", e.control.value)
        )

        sort_btn_global = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_sort("global")
        )
        
        my_students_col = ft.ListView(expand=True, spacing=10)
        global_students_col = ft.ListView(expand=True, spacing=10)
        
        def update_filters(target, value):
            if target == "my": state["filter_my_students"] = value.lower()
            else: state["filter_global_students"] = value.lower()
            render_student_lists()
        
        def toggle_sort(target):
            key = f"sort_{target}_students"
            state[key] = "desc" if state[key] == "asc" else "asc"
            btn = sort_btn_my if target == "my" else sort_btn_global
            btn.icon = ft.Icons.ARROW_DOWNWARD if state[key] == "asc" else ft.Icons.ARROW_UPWARD
            btn.update()
            render_student_lists()

        def load_students():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                # 1. Cargar MIS estudiantes (Clase actual)
                res_my = requests.get(f"{BASE}/api/teacher/students", headers=headers)
                if res_my.status_code == 200:
                    state["students"] = res_my.json()
                # 2. Cargar TODOS los estudiantes (Global del sistema)
                res_all = requests.get(f"{BASE}/api/teacher/all-users", headers=headers)
                if res_all.status_code == 200:
                    state["all_users_global"] = res_all.json()
                render_student_lists()
                update_dropdowns()
            except Exception as e:
                print(f"Error cargando estudiantes: {e}")

        def add_student_action(email_to_add):
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.post(f"{BASE}/api/teacher/students", headers=headers, json={"emails": [email_to_add]})
            if res.status_code == 200:
                flash(f"Estudiante {email_to_add} agregado", ok=True)
            else:
                flash("Error al agregar estudiante", ok=False)
            load_students()
            
        def delete_student(email):
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.delete(f"{BASE}/api/teacher/students", headers=headers, json={"email": email})
            if res.status_code == 200:
                flash(f"Estudiante {email} eliminado", ok=True)
            else:
                flash("Error al eliminar estudiante", ok=False)
            load_students()
            
        def render_student_lists():
            my_students_col.controls.clear()
            global_students_col.controls.clear()
            # --- 1. Filtrar y Ordenar MI CLASE ---
            mis_emails_raw = state["students"]
            mis_emails_filtrados = [e for e in mis_emails_raw if state["filter_my_students"] in e.lower()]
            mis_emails_filtrados.sort(reverse=(state["sort_my_students"] == "desc"))
            
            if not mis_emails_filtrados:
                msg = "No se encontraron resultados" if state["filter_my_students"] else "No tienes estudiantes aún"
                my_students_col.controls.append(ft.Text(msg, color=COLORES["subtitulo"]))
            else:
                for email in mis_emails_filtrados:
                    my_students_col.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.PERSON, color=COLORES["primario"], size=20),
                                ft.Text(email, expand=True, size=14, color=COLORES["texto"]),
                                ft.IconButton(
                                    ft.Icons.REMOVE_CIRCLE_OUTLINE, 
                                    icon_color=COLORES["error"], 
                                    tooltip="Quitar de mi clase",
                                    on_click=lambda e, mail=email: delete_student(mail)
                                )
                            ]),
                            bgcolor=COLORES["fondo"], 
                            padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                            border_radius=5, 
                            border=ft.border.all(1, COLORES["borde"])
                        )
                    )

            # --- 2. Filtrar y Ordenar GLOBAL ---
            set_mis_emails = set(mis_emails_raw)
            disponibles_raw = [u for u in state["all_users_global"] if u not in set_mis_emails]
            disponibles_filtrados = [e for e in disponibles_raw if state["filter_global_students"] in e.lower()]
            disponibles_filtrados.sort(reverse=(state["sort_global_students"] == "desc"))

            if not disponibles_filtrados:
                msg = "No se encontraron estudiantes inscritos" if state["filter_global_students"] else "No se encontraron estudiantes disponibles"
                global_students_col.controls.append(ft.Text(msg, color=COLORES["subtitulo"]))
            else:
                for email in disponibles_filtrados:
                    global_students_col.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.SCHOOL_OUTLINED, color=COLORES["primario"], size=20),
                                ft.Text(email, expand=True, size=14, color=COLORES["texto"]),
                                ft.IconButton(
                                    ft.Icons.ADD_CIRCLE_OUTLINE, 
                                    icon_color=COLORES["exito"], 
                                    tooltip="Agregar a mi clase",
                                    on_click=lambda e, mail=email: add_student_action(mail)
                                )
                            ]),
                            bgcolor=COLORES["fondo"], 
                            padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                            border_radius=5, 
                            border=ft.border.all(1, COLORES["borde"])
                        )
                    )
                    
            page.update()

        # Layout de la pestaña dividida
        tab_students = ft.Container(
            content=ft.Column([
                # Columnas divididas
                ft.Row([
                    # Columna izquierda: mis estudiantes
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Lista de estudiantes inscritos en mis materias", size=16, color=COLORES["primario"]),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar lista de estudiantes", on_click=lambda e: load_students())
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_students, sort_btn_my], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            my_students_col
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(right=5) # Margen entre columnas
                    ),
                    # Columna derecha: estudiantes disponibles
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Lista global de estudiantes disponibles", size=16, color=COLORES["primario"]),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar lista de estudiantes", on_click=lambda e: load_students())
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_global_students, sort_btn_global], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            global_students_col
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(left=5) # Margen entre columnas
                    )
                ], expand=True)
            ], expand=True), 
            padding=20
        )

        # =========================================
        # PESTAÑA 2: Mis Tareas
        # =========================================
        state["filter_my_tasks"] = ""
        state["sort_my_tasks"] = "asc"
        state["filter_global_tasks"] = ""
        state["sort_global_tasks"] = "asc"
        
        search_my_tasks = ft.TextField(
            hint_text="Buscar tareas en mi lista...",
            prefix_icon=ft.Icons.SEARCH,
            height=35,
            text_size=12,
            content_padding=10,
            border_radius=15,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            on_change=lambda e: update_task_filters("my", e.control.value)
        )
        
        sort_btn_my_tasks = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_task_sort("my")
        )

        search_global_tasks = ft.TextField(
            hint_text="Buscar tareas en el catálogo...",
            prefix_icon=ft.Icons.SEARCH,
            height=35,
            text_size=12,
            content_padding=10,
            border_radius=15,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            on_change=lambda e: update_task_filters("global", e.control.value)
        )

        sort_btn_global_tasks = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_task_sort("global")
        )
        
        col_available = ft.ListView(expand=True, spacing=10)
        col_mine = ft.ListView(expand=True, spacing=10)
        
        def update_task_filters(target, value):
            if target == "my": state["filter_my_tasks"] = value.lower()
            else: state["filter_global_tasks"] = value.lower()
            render_exercises()

        def toggle_task_sort(target):
            key = f"sort_{target}_tasks"
            state[key] = "desc" if state[key] == "asc" else "asc"
            btn = sort_btn_my_tasks if target == "my" else sort_btn_global_tasks
            btn.icon = ft.Icons.ARROW_DOWNWARD if state[key] == "asc" else ft.Icons.ARROW_UPWARD
            btn.update()
            render_exercises()
        
        def load_exercises():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                # 1. Cargar MIS ejercicios
                r1 = requests.get(f"{BASE}/api/teacher/my-exercises", headers=headers)
                if r1.status_code == 200:
                    state["my_exercises"] = r1.json()
                # 2. Cargar TODOS los del server
                r2 = requests.get(f"{BASE}/api/exercises/available", headers=headers)
                if r2.status_code == 200:
                    state["all_exercises"] = r2.json()
                render_exercises()
                update_dropdowns()
            except Exception as e:
                print(f"Error cargando ejercicios: {e}")

        def add_exercise(filename):
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.post(f"{BASE}/api/teacher/my-exercises", headers=headers, json={"filename": filename})
            if res.status_code == 200:
                flash(f"{filename} agregada a tu lista", ok=True)
            else:
                flash("Error al agregar tarea", ok=False)
            load_exercises()

        def remove_exercise(filename):
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.delete(f"{BASE}/api/teacher/my-exercises", headers=headers, json={"filename": filename})
            if res.status_code == 200:
                flash(f"{filename} eliminada de tu lista", ok=True)
            else:
                flash("Error al eliminar tarea", ok=False)
            load_exercises()

        def render_exercises():
            col_available.controls.clear()
            col_mine.controls.clear()
            safe_my_exercises = []
            
            for item in state["my_exercises"]:
                if isinstance(item, str):
                    safe_my_exercises.append({
                        "filename": item, "title": item, 
                        "description": "⚠️ Backend desactualizado.", "max_time": 0, "num_problems": 0
                    })
                else:
                    safe_my_exercises.append(item)
            
            safe_all_exercises = []
            
            for item in state["all_exercises"]:
                if isinstance(item, str):
                    safe_all_exercises.append({
                        "filename": item, "title": item, 
                        "description": "⚠️ Backend desactualizado.", "max_time": 0, "num_problems": 0
                    })
                else:
                    safe_all_exercises.append(item)

            my_filenames = {e["filename"] for e in safe_my_exercises}
            safe_available_exercises = [ex for ex in safe_all_exercises if ex["filename"] not in my_filenames]
            
            def create_exercise_card(ex_data, is_mine):
                minutes = ex_data.get('max_time', 0) // 60
                icono = ft.Icons.ASSIGNMENT if is_mine else ft.Icons.LIBRARY_BOOKS
                color_icono = COLORES["primario"]
                return ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(icono, size=20, color=color_icono),
                            ft.Text(ex_data.get("title", "Sin Título"), weight="bold", size=14, expand=True, color=COLORES["texto"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.IconButton(
                                ft.Icons.DELETE if is_mine else ft.Icons.ADD_CIRCLE, 
                                icon_color=COLORES["error"] if is_mine else COLORES["exito"],
                                tooltip="Quitar" if is_mine else "Agregar", 
                                icon_size=20,
                                on_click=lambda e, f=ex_data["filename"]: remove_exercise(f) if is_mine else add_exercise(f)
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
                        
                        ft.Text(ex_data.get("description", ""), size=12, italic=True, color=COLORES["subtitulo"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Container(height=5),
                        
                        ft.Row([
                            ft.Icon(ft.Icons.TIMER, size=14, color=COLORES["primario"]),
                            ft.Text(f"{minutes} minutos", size=12, color=COLORES["subtitulo"]),
                            ft.Container(width=10),
                            ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, size=14, color=COLORES["primario"]),
                            ft.Text(f"{ex_data.get('num_problems', 0)} ejercicios", size=12, color=COLORES["subtitulo"])
                        ])
                    ], spacing=2),
                    bgcolor=COLORES["fondo"], 
                    padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                    border_radius=5, 
                    border=ft.border.all(1, COLORES["borde"])
                )

            # --- 1. Filtrar y Ordenar MIS TAREAS ---
            filtered_mine = [e for e in safe_my_exercises if state["filter_my_tasks"] in e.get("title", "").lower()]
            filtered_mine.sort(key=lambda x: x.get("title", "").lower(), reverse=(state["sort_my_tasks"] == "desc"))
            
            if not filtered_mine:
                col_mine.controls.append(ft.Text("No tienes tareas asignadas.", color=COLORES["subtitulo"]))
            else:
                for ex in filtered_mine:
                    col_mine.controls.append(create_exercise_card(ex, True))

            # --- 2. Filtrar y Ordenar GLOBALES ---
            filtered_global = [e for e in safe_available_exercises if state["filter_global_tasks"] in e.get("title", "").lower()]
            filtered_global.sort(key=lambda x: x.get("title", "").lower(), reverse=(state["sort_global_tasks"] == "desc"))

            if not filtered_global:
                col_available.controls.append(ft.Text("No hay tareas disponibles.", color=COLORES["subtitulo"]))
            else:
                for ex in filtered_global:
                    col_available.controls.append(create_exercise_card(ex, False))
                
            page.update()

        # 5. Layout (Arquitectura clonada de Mis Estudiantes)
        tab_exercises = ft.Container(
            content=ft.Column([
                # Columnas divididas
                ft.Row([
                    # COLUMNA IZQUIERDA: MIS TAREAS
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Lista de tareas que forman parte de mis materias", size=16, color=COLORES["primario"]),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=lambda e: load_exercises())
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_tasks, sort_btn_my_tasks], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            col_mine
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(right=5) # Margen entre columnas
                    ),
                    # COLUMNA DERECHA: CATÁLOGO GLOBAL
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Catálogo global de tareas", size=16, color=COLORES["primario"]),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=lambda e: load_exercises())
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_global_tasks, sort_btn_global_tasks], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            col_available
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(left=5) # Margen entre columnas
                    )
                ], expand=True)
            ], expand=True), 
            padding=20
        )
        
        # =========================================
        # PESTAÑA 3: Monitoreo
        # =========================================
        answers_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        chats_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        
        student_filter = ft.Dropdown(
            label="Filtrar estudiante",
            options=[ft.dropdown.Option("Todos los estudiantes")], 
            value="Todos los estudiantes",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            on_change=lambda e: load_data_filtered(),
        )
        
        exercise_filter = ft.Dropdown(
            label="Filtrar tarea",
            options=[ft.dropdown.Option("Todas las tareas")], 
            value="Todas las tareas",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            on_change=lambda e: update_problem_options(),
        )
        
        problem_filter = ft.Dropdown(
            label="Filtrar ejercicio",
            options=[ft.dropdown.Option("Todos los ejercicios")],
            value="Todos los ejercicios",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            on_change=lambda e: load_data_filtered(),
            disabled=True,
        )
        
        def update_problem_options():
            selected_task = exercise_filter.value
            if not selected_task or selected_task == "Todas las tareas":
                problem_filter.options = [ft.dropdown.Option("Todos los ejercicios")]
                problem_filter.value = "Todos los ejercicios"
                problem_filter.disabled = True
            else:
                target = next((x for x in state["my_exercises"] if isinstance(x, dict) and x["filename"] == selected_task), None)
                if target:
                    num = target.get("num_problems", 1)
                    problem_filter.options = [ft.dropdown.Option("Todos los ejercicios")] + [ft.dropdown.Option(str(i)) for i in range(1, num + 1)]
                    problem_filter.disabled = False
                    problem_filter.value = "Todos los ejercicios"
                else:
                    problem_filter.disabled = True
            
            problem_filter.update()
            load_data_filtered()
            
        def update_dropdowns():
            student_filter.options = [ft.dropdown.Option("Todos los estudiantes")] + [ft.dropdown.Option(e) for e in state["students"]]
            exercise_filter.options = [ft.dropdown.Option("Todas las tareas")] + [
                ft.dropdown.Option(key=e["filename"], text=e["title"]) for e in state["my_exercises"] if isinstance(e, dict)
            ]
            problem_filter.value = "Todos los ejercicios"
            problem_filter.disabled = True
            page.update()
            
        # --- SECCIÓN MENSAJERÍA ---
        msg_info_text = ft.Text("", italic=True, color=COLORES["subtitulo"])
        
        msg_problem_dropdown = ft.Dropdown(
            label="Selecciona el Problema", 
            width=200,
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        
        msg_text_field = ft.TextField(
            label="Escribe tu mensaje...", 
            multiline=True, 
            min_lines=4,
            expand=True,
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        
        def close_dialog(e):
            dialog_msg.open = False
            page.update()
            
        def confirm_send(e):
            if not msg_text_field.value: 
                flash("El mensaje no puede estar vacío", ok=False)
                return
            if not msg_problem_dropdown.value:
                 flash("Selecciona un número de problema", ok=False)
                 return
                 
            reset_inactivity_timer() 
            
            res = auth_request("POST", "/api/teacher/send-message", json={
                "student_email": student_filter.value,
                "practice_name": exercise_filter.value,
                "problema_id": int(msg_problem_dropdown.value),
                "message": msg_text_field.value
            })
            
            if res and res.status_code == 200:
                dialog_msg.open = False
                flash("Mensaje enviado correctamente", ok=True)
                load_data_filtered() 
            else:
                flash("Error al enviar mensaje", ok=False)
            page.update()
            
        dialog_msg = ft.AlertDialog(
            title=ft.Text("Mensaje al Estudiante", color=COLORES["texto"]),
            content=ft.Container(
                content=ft.Column([
                    msg_info_text,
                    ft.Divider(), 
                    ft.Text("Selecciona el problema destino:", size=12, color=COLORES["subtitulo"]),
                    msg_problem_dropdown,
                    msg_text_field
                ], tight=True, spacing=15),
                width=600,
                height=350,
                bgcolor=COLORES["fondo"]
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.ElevatedButton("Enviar", on_click=confirm_send, bgcolor=COLORES["primario"], color=COLORES["fondo"])
            ],
            bgcolor=COLORES["fondo"]
        )
        
        page.overlay.append(dialog_msg)
        
        def send_direct_message(e):
            reset_inactivity_timer()
            student_email = student_filter.value
            task_filename = exercise_filter.value

            if not student_email or student_email == "Todos los estudiantes":
                flash("Debes seleccionar un estudiante específico para enviar un mensaje.", ok=False)
                return
            if not task_filename or task_filename == "Todas las tareas":
                flash("Debes seleccionar una tarea específica para enviar un mensaje.", ok=False)
                return

            target_exercise = next((item for item in state["my_exercises"] if isinstance(item, dict) and item["filename"] == task_filename), None)
            
            num_problems = 1
            ex_title = task_filename
            if target_exercise:
                num_problems = target_exercise.get("num_problems", 1)
                ex_title = target_exercise.get("title", task_filename)

            msg_info_text.value = f"Para: {student_email}\nTarea: {ex_title}"

            msg_problem_dropdown.options = [ft.dropdown.Option(str(i)) for i in range(1, num_problems + 1)]
            msg_problem_dropdown.value = "1"
            msg_text_field.value = ""

            dialog_msg.open = True
            page.update()
            
        def load_data_filtered(e=None):
            reset_inactivity_timer()
            params = {}
            if student_filter.value != "Todos los estudiantes":
                params["student_email"] = student_filter.value
            if exercise_filter.value != "Todas las tareas":
                params["practice_name"] = exercise_filter.value
                if problem_filter.value != "Todos los ejercicios" and problem_filter.value is not None:
                    pass
                    
            res = auth_request("GET", "/api/teacher/dashboard-data", params=params)
            if res and res.status_code == 200:
                render_data(res.json())
                
        def render_data(data):
            answers_col.controls.clear()
            chats_col.controls.clear()
            raw_answers = data.get("respuestas", [])
            raw_chats = data.get("chats", [])
            target_prob = problem_filter.value
            
            # --- FILTRO CLIENT-SIDE DE PROBLEMA ---
            if target_prob and target_prob.isdigit():
                pid = int(target_prob)
                raw_answers = [r for r in raw_answers if r['problema_id'] == pid]
                raw_chats = [c for c in raw_chats if c['problema_id'] == pid]
            
            for r in reversed(raw_answers): 
                answers_col.controls.append(ft.Container(content=ft.Column([
                    ft.Text(f"{r['correo']} - P{r['problema_id']}", size=12, color=COLORES["primario"], weight="bold"),
                    ft.Text(r['respuesta'], selectable=True, color=COLORES["texto"], size=13),
                    ft.Text(f"📅 {r['fecha'][:16].replace('T', ' ')}", size=10, color=COLORES["subtitulo"])
                ]), bgcolor=COLORES["fondo"], padding=10, border_radius=5, border=ft.border.all(1, COLORES["borde"])))
                
            for c in reversed(raw_chats):
                role = c.get('role', 'user')
                is_bot = role == 'assistant'
                is_teacher = role == 'teacher'
                
                align = ft.CrossAxisAlignment.START if (is_bot or is_teacher) else ft.CrossAxisAlignment.END
                
                if is_teacher: 
                    bg = COLORES["primario"]
                    txt_color = COLORES["fondo"]
                    label = f"PROFESOR ({c['correo']})"
                elif is_bot: 
                    bg = COLORES["borde"]
                    txt_color = COLORES["texto"]
                    label = "TUTOR IA"
                else: 
                    bg = COLORES["secundario"]
                    txt_color = COLORES["fondo"]
                    label = f"{c['correo']}"

                chats_col.controls.append(ft.Column([
                    ft.Text(f"{label} - P{c['problema_id']}", size=10, color=COLORES["subtitulo"]),
                    ft.Container(
                        content=ft.Text(c['content'], color=txt_color, size=13), 
                        bgcolor=bg, 
                        padding=10, 
                        border_radius=10,
                        width=None,
                    )
                ], horizontal_alignment=align))
            
            # Si no hay datos tras filtrar
            if not answers_col.controls:
                answers_col.controls.append(ft.Text("No hay respuestas registradas con estos filtros", italic=True, color=COLORES["subtitulo"]))
            if not chats_col.controls:
                chats_col.controls.append(ft.Text("No hay historial de chat con estos filtros", italic=True, color=COLORES["subtitulo"]))
            answers_col.update()
            chats_col.update()
            
        # =========================================
        # NAVEGACIÓN Y CARGA INICIAL
        # =========================================
        tab_monitor = ft.Container(
            content=ft.Column([
                # Fila Superior: Filtros
                ft.Container(
                    content=ft.Column([
                        ft.Text("Filtros de Monitoreo", size=16, color=COLORES["primario"]),
                        ft.Row([
                            student_filter, 
                            exercise_filter, 
                            problem_filter,
                            ft.IconButton(ft.Icons.SEARCH, icon_size=20, on_click=load_data_filtered, icon_color=COLORES["primario"], tooltip="Aplicar Filtros"),
                            ft.IconButton(ft.Icons.SEND, icon_size=20, on_click=send_direct_message, icon_color=COLORES["boton"], tooltip="Mensaje Directo")
                        ], spacing=10)
                    ]),
                    padding=10,
                    bgcolor=COLORES["accento"],
                    border_radius=10
                ),
                
                # Columnas divididas
                ft.Row([
                    # Columna izquierda: respuestas
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Registro de Respuestas", size=16, color=COLORES["primario"]),
                                ft.Icon(ft.Icons.QUESTION_ANSWER, size=20, color=COLORES["primario"])
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Divider(height=5, color="transparent"),
                            answers_col
                        ], expand=True),
                        expand=1,
                        bgcolor=COLORES["accento"],
                        padding=10,
                        border_radius=10,
                        margin=ft.margin.only(right=5) # Margen entre columnas
                    ),
                    # Columna derecha: chat
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Historial de Chat", size=16, color=COLORES["primario"]),
                                ft.Icon(ft.Icons.CHAT, size=20, color=COLORES["primario"])
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Divider(height=5, color="transparent"),
                            chats_col
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(left=5) # Margen entre columnas
                    )
                ], expand=True)
            ], expand=True), 
            padding=20
        )
        
        # =========================================
        # PESTAÑA 4: Dashboard (Tiempo Real)
        # =========================================

        # --- 2.4 LÓGICA DEL DASHBOARD (Botón Inicio + Grid) ---
        
        # Botón para iniciar/parar socket
        start_session_btn = ft.ElevatedButton(
            "Iniciar Sesión en Vivo", 
            icon=ft.Icons.PLAY_ARROW,
            bgcolor=COLORES["exito"],
            color=COLORES["texto"],
            height=40,
            on_click=lambda e: toggle_session(e)
        )

        def toggle_session(e):
            nonlocal is_session_active
            # Cambiar estado
            is_session_active = not is_session_active
            
            if is_session_active:
                # ACTIVAR
                start_session_btn.text = "Detener Sesión"
                start_session_btn.icon = ft.Icons.STOP
                start_session_btn.bgcolor = COLORES["error"]
                session_status_text.value = "🔴 EN VIVO: Recibiendo alertas..."
                session_status_text.color = COLORES["error"]
                
                # Conectar SocketIO
                try:
                    if not sio.connected:
                        sio.connect(BASE) # Usa la URL base (Railway o Localhost)
                except Exception as err:
                        print(f"Socket Error: {err}")
                        flash(f"Error conectando: {err}", ok=False)
                        # Revertir si falla
                        is_session_active = False
                        toggle_session(None) 
                        return
            else:
                # DESACTIVAR
                start_session_btn.text = "Iniciar Sesión en Vivo"
                start_session_btn.icon = ft.Icons.PLAY_ARROW
                start_session_btn.bgcolor = COLORES["exito"]
                session_status_text.value = "Sesión Inactiva"
                session_status_text.color = COLORES["subtitulo"]
                if sio.connected:
                    sio.disconnect()
                    
            page.update()

        def load_full_dashboard():
            # Carga datos históricos iniciales
            reset_inactivity_timer()
            # Obtenemos lista de estudiantes para pintar las tarjetas iniciales
            render_dashboard_view(state["students"])

        def render_dashboard_view(student_list):
            dashboard_grid.controls.clear()
            student_cards_state.clear() # Limpiar estado anterior

            if not student_list:
                dashboard_grid.controls.append(ft.Text("No hay estudiantes registrados", size=16))
                page.update()
                return

            # Calcular totales para barra de progreso (usando ejercicios cargados)
            safe_exercises = [x for x in state["my_exercises"] if isinstance(x, dict)]
            total_tasks = len(safe_exercises)
            
            # --- CONSTRUIR TARJETAS ---
            for stu in student_list:
                # Estado inicial visual
                initial_color = COLORES["borde"]
                initial_icon = ft.Icons.CIRCLE_OUTLINED
                
                # Calcular progreso (simulado o real si tienes datos históricos)
                # Por ahora iniciamos en 0% o lo que tengas en DB
                progress_pct = 0 
                
                # Tarjeta Interactiva
                card_content = ft.Column([
                        ft.Row([
                            ft.Column([
                                ft.Text(stu.split("@")[0], weight="bold", size=16, no_wrap=True, color=COLORES["texto"]),
                                ft.Text(stu, size=10, color=COLORES["subtitulo"], no_wrap=True),
                            ], expand=True),
                            # Icono de Estado (Cambiará con SocketIO)
                            ft.Icon(initial_icon, color=initial_color, size=24),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
                        ft.Divider(height=10, color="transparent"),
                        
                        # Barra de progreso
                        ft.ProgressBar(value=progress_pct, color=COLORES["primario"], bgcolor=COLORES["borde"], height=6, border_radius=3),
                        ft.Text(f"Esperando actividad...", size=10, italic=True, color=COLORES["subtitulo"]),
                        
                        ft.Divider(height=5, color="transparent"),
                        
                        # Botón Ver Análisis
                        ft.ElevatedButton(
                            "Ver Análisis", 
                            icon=ft.Icons.VISIBILITY, 
                            height=30, 
                            style=ft.ButtonStyle(
                                padding=5, 
                                shape=ft.RoundedRectangleBorder(radius=5),
                                color=COLORES["primario"],
                                bgcolor=COLORES["accento"]
                            ),
                            on_click=lambda e, email=stu: show_student_detail(email)
                        )
                    ])

                card = ft.Container(
                    content=card_content,
                    bgcolor=COLORES["fondo"], # Fondo de tarjeta
                    padding=15,
                    border_radius=15,
                    shadow=ft.BoxShadow(blur_radius=10, color=COLORES["accento"]),
                    border=ft.border.all(2, initial_color), # El borde cambiará de color
                    data=stu 
                )
                
                # GUARDAR REFERENCIA PARA ACTUALIZAR DESPUÉS
                student_cards_state[stu] = {'control': card}
                dashboard_grid.controls.append(card)
                
            page.update()

        tab_dashboard = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("Dashboard en Tiempo Real", size=24, weight="bold", color=COLORES["primario"]),
                        session_status_text # Variable global definida arriba
                    ]),
                    ft.Row([
                        start_session_btn, 
                        ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], tooltip="Reiniciar Vista", on_click=lambda e: load_full_dashboard())
                    ])
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                
                ft.Divider(color=COLORES["borde"]),
                
                # GRID DE ESTUDIANTES GLOBAL (definido al inicio del archivo)
                dashboard_grid 
            ], expand=True),
            padding=20
        )

        # GRADING: Define Grading Tab Layout
        grading_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        grade_score_field = ft.TextField(label="Calificación (0-10)", width=100)
        grade_comment_field = ft.TextField(label="Comentario", multiline=True)
        grade_student_label = ft.Text("", weight="bold") 
        grade_task_label = ft.Text("", size=12)
        grade_response_container = ft.Container(bgcolor=COLORES["fondo"], padding=10)
        grade_btn_approve = ft.ElevatedButton("Aprobar IA", bgcolor=COLORES["exito"], color=COLORES["texto"])
        grade_btn_save = ft.ElevatedButton("Guardar Cambios", bgcolor=COLORES["boton"], color=COLORES["texto"])
        
        grade_dlg = ft.AlertDialog(
            title=grade_student_label,
            content=ft.Column([
                grade_task_label,
                ft.Text("Respuesta del Estudiante:", weight="bold"),
                grade_response_container,
                ft.Divider(),
                ft.Text("Sugerencia IA:", color=COLORES["primario"]),
                grade_score_field,
                grade_comment_field
            ], tight=True, width=500),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: close_grade_dlg()),
                grade_btn_approve,
                grade_btn_save,
            ]
        )
        
        page.overlay.append(grade_dlg)

        def close_grade_dlg():
            grade_dlg.open = False
            page.update()

        def submit_grade(item_id, score, comment, action):
            res = auth_request("POST", "/api/teacher/grades/submit", json={
                "id": item_id,
                "score": score,
                "comment": comment,
                "action": action
            })
            if res and res.status_code == 200:
                flash("Evaluación guardada", ok=True)
                grade_dlg.open = False
                page.update()
                load_pending_grades()
            else:
                flash("Error al guardar", ok=False)

        def open_grade_dialog(item):
            grade_student_label.value = f"Evaluar: {item['correo']}"
            grade_task_label.value = f"Práctica: {item['practica']} | Ej: {item['problema_id']}"
            grade_response_container.content = ft.Text(item['respuesta'])
            grade_score_field.value = str(item['llm_score'])
            grade_comment_field.value = item['llm_comment']

            grade_btn_approve.on_click = lambda e: submit_grade(
                item['id'], item['llm_score'], item['llm_comment'], "approve"
            )
            
            grade_btn_save.on_click = lambda e: submit_grade(
                item['id'], grade_score_field.value, grade_comment_field.value, "edit"
            )

            grade_dlg.open = True
            page.update()

        def load_pending_grades():
            res = auth_request("GET", "/api/teacher/grades/pending")
            if res and res.status_code == 200:
                render_grading_view(res.json())

        def render_grading_view(items):
            grading_col.controls.clear()
            if not items:
                grading_col.controls.append(ft.Text("No hay evaluaciones pendientes 🎉", size=20))
                page.update()
                return

            for item in items:
                card = ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(item['correo'], weight="bold"),
                            ft.Text(f"{item['practica']} - P{item['problema_id']}", size=12, color=COLORES["subtitulo"])
                        ], expand=True),
                        ft.Column([
                            ft.Text(f"Nota IA: {item['llm_score']}", color=COLORES["primario"], weight="bold"),
                            ft.Text("Pendiente", size=10, italic=True)
                        ]),
                        ft.IconButton(ft.Icons.EDIT, on_click=lambda e, i=item: open_grade_dialog(i))
                    ]),
                    bgcolor=COLORES["accento"], padding=10, border_radius=5, margin=5
                )
                grading_col.controls.append(card)
            page.update()

        tab_grading = ft.Container(
            content=ft.Column([
                ft.Row([ft.Text("Evaluaciones Pendientes", size=20, weight="bold"), 
                        ft.IconButton(ft.Icons.REFRESH, on_click=lambda e: load_pending_grades())]),
                grading_col
            ], expand=True),
            padding=20
        )
        # Tabs Principales
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            on_change=lambda e: (
                reset_inactivity_timer(),
                load_exercises() if e.control.selected_index == 1 else None,
                load_pending_grades() if e.control.selected_index == 2 else None,
                load_full_dashboard() if e.control.selected_index == 4 else None
            ),
            tabs=[
                ft.Tab(text="Mis Estudiantes", icon=ft.Icons.GROUPS, content=tab_students),
                ft.Tab(text="Mis Tareas", icon=ft.Icons.ASSIGNMENT, content=tab_exercises),
                ft.Tab(text="Evaluaciones", icon=ft.Icons.GRADE, content=tab_grading),
                ft.Tab(text="Monitoreo", icon=ft.Icons.INSIGHTS, content=tab_monitor),
                ft.Tab(text="Dashboard", icon=ft.Icons.DASHBOARD, content=tab_dashboard)
            ], expand=True
        )

        # --- HEADER PRINCIPAL (Centrado + Tema + Logout) ---
        header = ft.Container(
            content=ft.Row(
                [
                    # Botón de Tema (Usa el icono inverso al tema actual para indicar "cambiar a")
                    ft.IconButton(
                        icon=ft.Icons.LIGHT_MODE if theme_name == "dark" else ft.Icons.DARK_MODE,
                        icon_color=COLORES["primario"],
                        tooltip="Cambiar Tema",
                        on_click=toggle_theme
                    ),
                    
                    # Título Centrado
                    ft.Row(
                        [ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE, color=COLORES["primario"]), 
                         ft.Text("Panel Profesor", size=24, weight="bold", color=COLORES["texto"])],
                        alignment=ft.MainAxisAlignment.CENTER,
                        expand=True 
                    ),
                    
                    # Logout
                    ft.IconButton(
                        ft.Icons.LOGOUT, 
                        icon_color=COLORES["error"], 
                        tooltip="Cerrar Sesión",
                        on_click=lambda e: (page.client_storage.remove("teacher_token"), show_login())
                    )
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            ),
            padding=ft.padding.symmetric(horizontal=20, vertical=10),
            bgcolor=COLORES["accento"],
            border_radius=ft.border_radius.only(bottom_left=15, bottom_right=15),
            shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"])
        )
        
        page.add(
            ft.Column([
                header,
                tabs
            ], expand=True)
        )
        
        load_students()
        load_exercises()

    stored_token = page.client_storage.get("teacher_token")
    last_act_stored = page.client_storage.get("last_activity")
    
    if stored_token and last_act_stored:
        if time.time() - last_act_stored > 3600:
             page.client_storage.remove("teacher_token")
             show_login()
        else:
            state["token"] = stored_token
            state["last_activity"] = last_act_stored
            show_dashboard()
    else:
        show_login()

if __name__ == "__main__":
    print(f"📂 RUTA ASSETS FINAL: {ASSETS_PATH}")
    if os.path.exists(ASSETS_PATH):
        print(f"✅ Archivos en assets: {os.listdir(ASSETS_PATH)}")
    else:
        print(f"❌ ADVERTENCIA: No se encuentra la carpeta en: {ASSETS_PATH}")

    os.environ["FLET_FORCE_WEB"] = "1"
    port = int(os.getenv("PORT", "3001"))
    
    ft.app(
        target=main, 
        view=ft.AppView.WEB_BROWSER, 
        host="0.0.0.0", 
        port=port, 
        assets_dir=ASSETS_PATH
    )
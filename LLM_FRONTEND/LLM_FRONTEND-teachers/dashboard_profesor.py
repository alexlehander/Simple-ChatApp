import flet as ft
import requests, time, threading, os, json
import socketio
import datetime as dt
from zoneinfo import ZoneInfo

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

def main(page: ft.Page):
    ui_lock = threading.Lock()
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
    detail_dlg_title = ft.Text(weight="bold", size=20)
    detail_dlg_content = ft.ListView(spacing=15, padding=ft.padding.only(right=20))
        
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
        detail_dlg_title.value = f"Línea de Tiempo: {email.split('@')[0]}"
        
        def fetch_and_render_timeline():
            timeline_data = []
            try:
                res = auth_request("GET", f"/api/student_timeline/{email}", timeout=10)
                if res and res.status_code == 200:
                    timeline_data = res.json()
            except Exception as e:
                print(f"Error fetching timeline: {e}")
                
            def get_status_meta(color_name):
                return {
                    "green": (ft.Icons.CHECK_CIRCLE_OUTLINED, COLORES["exito"]),
                    "yellow": (ft.Icons.WARNING_AMBER_ROUNDED, COLORES["advertencia"]),
                    "red": (ft.Icons.ERROR_OUTLINED, COLORES["error"])
                }.get(color_name, (ft.Icons.CIRCLE_OUTLINED, COLORES["subtitulo"]))
                
            nuevos_controles = []
            if not timeline_data:
                nuevos_controles.append(
                    ft.Container(
                        content=ft.Text("No hay interacciones recientes registradas.", italic=True, color=COLORES["subtitulo"]),
                        alignment=ft.alignment.center, padding=20
                    )
                )
            else:
                for event in timeline_data:
                    try:
                        import datetime as dt_module
                        dt_obj = dt_module.datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                        dt_local = dt_obj - dt_module.timedelta(hours=8)
                        time_str = dt_local.strftime("%I:%M %p - %d/%b")
                    except Exception as e:
                        time_str = event['timestamp'][:10]
                        
                    icon_shape, icon_color = get_status_meta(event['color'])
                    event_icon = ft.Icons.CHAT_BUBBLE_OUTLINED if event['type'] == 'chat' else ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED
                    
                    item_row = ft.Container(
                        content=ft.Row([
                            ft.Column([
                                 ft.Text(time_str, size=10, color=COLORES["subtitulo"]),
                                 ft.Icon(event_icon, color=COLORES["primario"], size=20),
                            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                            
                            ft.Container(width=2, height=40, bgcolor=COLORES["borde"]),
                            
                            ft.Row([
                                 ft.Column([
                                    ft.Text(event['description'], weight="bold", size=14, color=COLORES["texto"]),
                                    ft.Text(f"Tipo: {event['type'].title()} | Etiqueta: {event['color'].title()}", size=11, color=COLORES["subtitulo"]),
                                 ], expand=True, spacing=2),
                                 ft.Icon(icon_shape, color=icon_color, size=24)
                            ], expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                        ], spacing=15),
                        padding=ft.padding.symmetric(vertical=10, horizontal=5),
                        border=ft.border.only(bottom=ft.border.BorderSide(1, COLORES["borde"]))
                    )
                    nuevos_controles.append(item_row)
                    
            detail_dlg_content.controls = nuevos_controles
            
            try:
                if detail_dlg.open:
                    detail_dlg_content.update()
            except Exception:
                pass
                
        def trigger_load(e=None):
            detail_dlg_content.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.ProgressRing(color=COLORES["primario"], stroke_width=4),
                        ft.Text("Consultando historial académico...", color=COLORES["subtitulo"], italic=True)
                    ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    alignment=ft.alignment.center,
                    height=200
                )
            ]
            if detail_dlg.open:
                detail_dlg_content.update()
                
            threading.Thread(target=fetch_and_render_timeline, daemon=True).start()

        detail_dlg.actions = [
            ft.TextButton("Refrescar", icon=ft.Icons.REFRESH, icon_color=COLORES["primario"], on_click=trigger_load),
            ft.TextButton("Cerrar", on_click=lambda e: close_detail_dlg())
        ]

        detail_dlg.content.width = 800
        detail_dlg.content.height = 600
        detail_dlg.open = True
        page.update()
        
        trigger_load()
        
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
        prog_pct = data.get('progress_pct', 0.0)
        print(f"⚡ Actividad recibida: {email} - {status_color} - Progreso: {prog_pct*100}%")
    
        if email in student_cards_state:
            card_data = student_cards_state[email]
            card_control = card_data['control']
            bar_ctrl = card_data['bar_ctrl']
            txt_ctrl = card_data['txt_ctrl']
            
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
    
            card_control.border = ft.border.all(3, new_color)
            status_icon_control = card_control.content.controls[0].controls[1]
            status_icon_control.name = icon_data[0]
            status_icon_control.color = icon_data[1]
            bar_ctrl.value = prog_pct
            
            if data.get('type') == 'answer':
                txt_ctrl.value = f"Entregó P{data.get('problem_id', '?')} ({(prog_pct*100):.0f}%)"
            else:
                txt_ctrl.value = f"Conversando ({(prog_pct*100):.0f}%)"
            
            card_data['latest_data'] = data
            
            try:
                if card_control.page:
                    bar_ctrl.update()
                    txt_ctrl.update()
                    card_control.update()
            except AssertionError:
                pass
                
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
        with ui_lock:
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
    
    def show_login():
        page.clean()
        
        # --- 1. Lógica y Controles ---
        email_field = ft.TextField(
            label="Correo", 
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
                
            e.control.disabled = True
            page.update()
            
            try:
                res = requests.post(f"{BASE}/api/teacher/login", json={"email": email_field.value, "password": pass_field.value}, timeout=10)
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
                        msg_error = res.json().get("msg", "Credenciales inválidas")
                    except:
                        msg_error = f"Error del servidor ({res.status_code}) o Credenciales incorrectas"
                    flash(msg_error, ok=False)
                    
            except Exception as ex:
                print(f"Login error: {ex}")
                flash("Error de conexión o servidor", ok=False)
            finally:
                e.control.disabled = False
                page.update()

        def register_action(e):
            if not email_field.value or not pass_field.value:
                flash("Por favor, ingresa correo y contraseña para registrar nueva cuenta docente", ok=False)
                return
                
            e.control.disabled = True
            page.update()
            
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
            finally:
                e.control.disabled = False
                page.update()
                
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

        background_image = ft.Image(
            src="fondo_login.jpg",
            fit=ft.ImageFit.COVER,
            opacity=1.0,
            gapless_playback=True
        )

        layout_login = ft.Stack(
            controls=[
                ft.Container(
                    content=background_image,
                    left=0,
                    top=0,
                    right=0,
                    bottom=0
                ),
                ft.Container(
                    content=card,
                    alignment=ft.alignment.center,
                    left=0,
                    top=0,
                    right=0,
                    bottom=0
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
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_filters("my", e.control.value)
        )
        
        search_global_students = ft.TextField(
            hint_text="Buscar estudiantes disponibles...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_filters("global", e.control.value)
        )
        
        sort_btn_my = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_sort("my")
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
            render_students()
        
        def toggle_sort(target):
            key = f"sort_{target}_students"
            state[key] = "desc" if state[key] == "asc" else "asc"
            btn = sort_btn_my if target == "my" else sort_btn_global
            btn.icon = ft.Icons.ARROW_DOWNWARD if state[key] == "asc" else ft.Icons.ARROW_UPWARD
            render_students()
            
        def load_students():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                res_my = requests.get(f"{BASE}/api/teacher/students", headers=headers)
                if res_my.status_code == 200:
                    state["students"] = res_my.json()
                res_all = requests.get(f"{BASE}/api/teacher/all-users", headers=headers)
                if res_all.status_code == 200:
                    state["all_users_global"] = res_all.json()
                render_students()
                update_dropdowns()
            except Exception as e:
                print(f"Error cargando estudiantes: {e}")
                
        def refresh_students(e):
            e.control.disabled = True
            page.update()
            load_students()
            e.control.disabled = False
            page.update()
            
        def add_student_action(e, email_to_add):
            e.control.disabled = True
            page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.post(f"{BASE}/api/teacher/students", headers=headers, json={"emails": [email_to_add]})
            if res.status_code == 200:
                flash(f"Estudiante {email_to_add} agregado", ok=True)
            else:
                flash("Error al agregar estudiante", ok=False)
            load_students()
            
        def delete_student(e, email):
            e.control.disabled = True
            page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.delete(f"{BASE}/api/teacher/students", headers=headers, json={"email": email})
            if res.status_code == 200:
                flash(f"Estudiante {email} eliminado", ok=True)
            else:
                flash("Error al eliminar estudiante", ok=False)
            load_students()
            
        def render_students():
            with ui_lock:
                nuevos_locales = []
                nuevos_globales = []
                
                # --- 2. Filtrar y Ordenar LOCAL ---
                mis_estudiantes = state.get("students", [])
                busqueda_my = state["filter_my_students"]
                mis_filtrados = [s for s in mis_estudiantes if busqueda_my in s["email"].lower() or busqueda_my in s.get("nombre", "").lower()]
                mis_filtrados.sort(key=lambda x: x.get("nombre", "").lower(), reverse=(state["sort_my_students"] == "desc"))
                if not mis_filtrados:
                    msg = "No se encontraron resultados" if busqueda_my else "No hay estudiantes inscritos"
                    nuevos_locales.append(ft.Text(msg, color=COLORES["subtitulo"]))
                else:
                    for s in mis_filtrados:
                        nuevos_locales.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.PERSON, color=COLORES["primario"], size=30),
                                    ft.Column([
                                        ft.Text(s.get("nombre", "Estudiante"), weight="bold", size=16, color=COLORES["texto"]),
                                        ft.Text(s["email"], size=14, color=COLORES["subtitulo"])
                                    ], expand=True, spacing=2),
                                    ft.IconButton(
                                        ft.Icons.REMOVE_CIRCLE_OUTLINE, 
                                        icon_color=COLORES["error"], 
                                        tooltip="Quitar de mi clase",
                                        on_click=lambda e, mail=s["email"]: delete_student(e, mail)
                                    )
                                ]),
                                bgcolor=COLORES["fondo"], 
                                padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                                border_radius=5, 
                                border=ft.border.all(1, COLORES["borde"])
                            )
                        )
                        
                # --- 2. Filtrar y Ordenar GLOBAL ---
                set_mis_emails = {s["email"] for s in mis_estudiantes}
                disponibles_raw = [u for u in state.get("all_users_global", []) if u["email"] not in set_mis_emails]
                busqueda_global = state["filter_global_students"]
                disponibles_filtrados = [s for s in disponibles_raw if busqueda_global in s["email"].lower() or busqueda_global in s.get("nombre", "").lower()]
                disponibles_filtrados.sort(key=lambda x: x.get("nombre", "").lower(), reverse=(state["sort_global_students"] == "desc"))
                if not disponibles_filtrados:
                    msg = "No se encontraron estudiantes" if busqueda_global else "No hay estudiantes disponibles"
                    nuevos_globales.append(ft.Text(msg, color=COLORES["subtitulo"]))
                else:
                    for s in disponibles_filtrados:
                        nuevos_globales.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.SCHOOL_OUTLINED, color=COLORES["primario"], size=30),
                                    ft.Column([
                                        ft.Text(s.get("nombre", "Estudiante"), weight="bold", size=16, color=COLORES["texto"]),
                                        ft.Text(s["email"], size=14, color=COLORES["subtitulo"])
                                    ], expand=True, spacing=2),
                                    ft.IconButton(
                                        ft.Icons.ADD_CIRCLE_OUTLINE, 
                                        icon_color=COLORES["exito"], 
                                        tooltip="Agregar a mi clase",
                                        on_click=lambda e, mail=s["email"]: add_student_action(e, mail)
                                    )
                                ]),
                                bgcolor=COLORES["fondo"], 
                                padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                                border_radius=5, 
                                border=ft.border.all(1, COLORES["borde"])
                            )
                        )
                my_students_col.controls = nuevos_locales
                global_students_col.controls = nuevos_globales
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
                                ft.Text("Lista de estudiantes inscritos", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar lista de estudiantes", on_click=refresh_students)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_students, sort_btn_my], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            my_students_col
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(right=5)
                    ),
                    # Columna derecha: estudiantes disponibles
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Lista de estudiantes disponibles", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar lista de estudiantes", on_click=refresh_students)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_global_students, sort_btn_global], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            global_students_col
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(left=5)
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
            hint_text="Buscar tareas seleccionadas...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_task_filters("my", e.control.value)
        )
        
        search_global_tasks = ft.TextField(
            hint_text="Buscar tareas disponibles...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_task_filters("global", e.control.value)
        )
        
        sort_btn_my_tasks = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_task_sort("my")
        )
        
        sort_btn_global_tasks = ft.IconButton(
            icon=ft.Icons.SORT_BY_ALPHA,
            tooltip="Ordenar A-Z / Z-A",
            icon_color=COLORES["primario"],
            on_click=lambda e: toggle_task_sort("global")
        )
        
        col_available = ft.ListView(expand=True, spacing=10)
        col_mine = ft.ListView(expand=True, spacing=10)
        ex_detail_dlg_title = ft.Text("", weight="bold", size=20, color=COLORES["primario"], text_align=ft.TextAlign.CENTER)
        ex_detail_dlg_content = ft.ListView(spacing=10)
        
        ex_detail_dlg = ft.AlertDialog(
            title=ex_detail_dlg_title,
            content=ft.Container(content=ex_detail_dlg_content, width=700, height=500, padding=10),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: close_ex_detail_dlg())],
            on_dismiss=lambda e: close_ex_detail_dlg()
        )
        
        page.overlay.append(ex_detail_dlg)
        
        def close_ex_detail_dlg():
            ex_detail_dlg.open = False
            page.update()
            
        def show_exercise_detail(filename):
            ex_detail_dlg_title.value = "Cargando detalles..."
            ex_detail_dlg_content.controls = [
                ft.Container(
                    content=ft.ProgressRing(color=COLORES["primario"], stroke_width=4),
                    alignment=ft.alignment.center,
                    height=200
                )
            ]
            ex_detail_dlg.open = True
            page.update()
            
            def fetch_and_render_ex():
                try:
                    res = auth_request("GET", f"/api/exercises/detail/{filename}", timeout=10)
                    if res and res.status_code == 200:
                        data = res.json()
                        title = data.get("title", filename)
                        desc = data.get("description", "Sin descripción")
                        max_time = data.get("max_time", 0) // 60
                        problemas = data.get("problemas", [])
                        
                        ex_detail_dlg_title.value = title
                        
                        info_col = ft.Container(
                            content=ft.Column([
                                ft.Text(desc, color=COLORES["texto"], text_align=ft.TextAlign.JUSTIFY),
                                ft.Row([
                                    ft.Icon(ft.Icons.TIMER, size=16, color=COLORES["subtitulo"]),
                                    ft.Text(f"Tiempo límite para resolver la tarea: {max_time} minutos", color=COLORES["subtitulo"], italic=True)
                                ], alignment=ft.MainAxisAlignment.CENTER),
                                ft.Divider(color=COLORES["borde"], height=20),
                                ft.Text(f"{len(problemas)} Ejercicios Incluidos", weight="bold", size=16, color=COLORES["primario"], text_align=ft.TextAlign.CENTER)
                            ], 
                            spacing=5, 
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            margin=ft.margin.symmetric(horizontal=15)
                        )
                        prob_list = []
                        if not problemas:
                            prob_list.append(ft.Text("No hay ejercicios configurados en esta práctica", color=COLORES["subtitulo"], italic=True))
                        else:
                            for p in problemas:
                                prob_list.append(
                                    ft.Container(
                                        content=ft.Column([
                                            ft.Text(f"Problema {p.get('id', '?')}", weight="bold", color=COLORES["secundario"], size=14),
                                            ft.Text(p.get("enunciado", "Sin enunciado"), color=COLORES["texto"], size=13, text_align=ft.TextAlign.JUSTIFY)
                                        ], spacing=5),
                                        bgcolor=COLORES["fondo"],
                                        padding=ft.padding.only(left=10, top=5, right=20, bottom=5), 
                                        border_radius=8,
                                        border=ft.border.all(1, COLORES["borde"]),
                                    )
                                )
                        ex_detail_dlg_content.controls = [info_col] + prob_list
                    else:
                        ex_detail_dlg_content.controls = [ft.Text("No se pudo cargar la información de la tarea.", color=COLORES["error"])]
                except Exception as e:
                    print(f"Error fetch detail: {e}")
                    ex_detail_dlg_content.controls = [ft.Text("Error de conexión al cargar detalles.", color=COLORES["error"])]
                    
                try:
                    if ex_detail_dlg.open:
                        ex_detail_dlg.update()
                except Exception:
                    pass
                    
            threading.Thread(target=fetch_and_render_ex, daemon=True).start()
        
        def update_task_filters(target, value):
            if target == "my": state["filter_my_tasks"] = value.lower()
            else: state["filter_global_tasks"] = value.lower()
            render_exercises()

        def toggle_task_sort(target):
            key = f"sort_{target}_tasks"
            state[key] = "desc" if state[key] == "asc" else "asc"
            btn = sort_btn_my_tasks if target == "my" else sort_btn_global_tasks
            btn.icon = ft.Icons.ARROW_DOWNWARD if state[key] == "asc" else ft.Icons.ARROW_UPWARD
            render_exercises()
        
        def load_exercises():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                r1 = requests.get(f"{BASE}/api/teacher/my-exercises", headers=headers)
                if r1.status_code == 200:
                    state["my_exercises"] = r1.json()
                r2 = requests.get(f"{BASE}/api/exercises/available", headers=headers)
                if r2.status_code == 200:
                    state["all_exercises"] = r2.json()
                render_exercises()
                update_dropdowns()
            except Exception as e:
                print(f"Error cargando ejercicios: {e}")
                
        def refresh_exercises(e):
            e.control.disabled = True
            page.update()
            load_exercises()
            e.control.disabled = False
            page.update()
            
        def add_exercise(e, filename):
            e.control.disabled = True
            page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.post(f"{BASE}/api/teacher/my-exercises", headers=headers, json={"filename": filename})
            if res.status_code == 200:
                flash(f"{filename} agregada a tu lista", ok=True)
            else:
                flash("Error al agregar tarea", ok=False)
            load_exercises()

        def remove_exercise(e, filename):
            e.control.disabled = True
            page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.delete(f"{BASE}/api/teacher/my-exercises", headers=headers, json={"filename": filename})
            if res.status_code == 200:
                flash(f"{filename} eliminada de tu lista", ok=True)
            else:
                flash("Error al eliminar tarea", ok=False)
            load_exercises()
            
        def toggle_exercise_status(e, filename):
            e.control.disabled = True
            page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.put(f"{BASE}/api/teacher/my-exercises/toggle", headers=headers, json={"filename": filename})
            if res.status_code == 200:
                data = res.json()
                is_active = data.get("is_active", False)
                status_str = "Activo (visible para estudiantes)" if is_active else "Inactivo (oculto para estudiantes)"
                flash(f"Ejercicio {status_str}", ok=is_active)
                load_exercises() # Recargar para actualizar los colores de la UI
            else:
                flash("Error al cambiar estado", ok=False)
                
        def render_exercises():
            with ui_lock:
                safe_my_exercises = []
                nuevas_mias = []
                nuevas_disponibles = []
                
                for item in state["my_exercises"]:
                    if isinstance(item, str):
                        safe_my_exercises.append({
                            "filename": item, "title": item, 
                            "description": "⚠️ Backend desactualizado.", "max_time": 0, "num_problems": 0, "is_active": False
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
                    top_row_controls = [
                        ft.Icon(icono, size=20, color=color_icono)
                    ]
                    
                    if is_mine:
                        is_active = ex_data.get("is_active", False)
                        btn_color = COLORES["exito"] if is_active else COLORES["error"]
                        btn_icon = ft.Icons.VISIBILITY if is_active else ft.Icons.VISIBILITY_OFF
                        btn_tooltip = "Visible para estudiantes (click para ocultar)" if is_active else "Oculto para estudiantes (click para visualizar)"
                        
                        toggle_btn = ft.IconButton(
                            icon=btn_icon,
                            icon_color=btn_color,
                            tooltip=btn_tooltip,
                            icon_size=20,
                            on_click=lambda e, f=ex_data["filename"]: toggle_exercise_status(e, f)
                        )
                        top_row_controls.append(toggle_btn)
                        
                    title_text = ft.Text(
                        ex_data.get("title", "Sin Título"), 
                        weight="bold", 
                        size=16, 
                        expand=True, 
                        color=COLORES["texto"], 
                        max_lines=2, 
                        overflow=ft.TextOverflow.ELLIPSIS
                    )
                    top_row_controls.append(title_text)
                    
                    if is_mine:
                        del_btn = ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_color=COLORES["error"],
                            tooltip="Quitar de mi lista",
                            icon_size=20,
                            on_click=lambda e, f=ex_data["filename"]: remove_exercise(e, f)
                        )
                        top_row_controls.append(del_btn)
                    else:
                        add_btn = ft.IconButton(
                            icon=ft.Icons.ADD_CIRCLE, 
                            icon_color=COLORES["exito"],
                            tooltip="Agregar a mis tareas", 
                            icon_size=20,
                            on_click=lambda e, f=ex_data["filename"]: add_exercise(e, f)
                        )
                        top_row_controls.append(add_btn)
                        
                    borde_color = COLORES["borde"]
                    if is_mine:
                        borde_color = COLORES["exito"] if ex_data.get("is_active") else COLORES["error"]
                        
                    return ft.Container(
                        content=ft.Column([
                            ft.Row(top_row_controls, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            
                            ft.Text(ex_data.get("description", ""), size=14, italic=True, color=COLORES["subtitulo"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Container(height=5),
                            
                            ft.Row([
                                ft.Icon(ft.Icons.TIMER, size=14, color=COLORES["primario"]),
                                ft.Text(f"{minutes} minutos", size=14, color=COLORES["subtitulo"]),
                                ft.Container(width=10),
                                ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, size=14, color=COLORES["primario"]),
                                ft.Text(f"{ex_data.get('num_problems', 0)} ejercicios", size=12, color=COLORES["subtitulo"])
                            ])
                        ], spacing=5),
                        bgcolor=COLORES["fondo"], 
                        padding=ft.padding.only(left=10, top=5, right=20, bottom=5),
                        border_radius=5, 
                        border=ft.border.all(1, borde_color),
                        ink=True, 
                        on_click=lambda e, f=ex_data["filename"]: show_exercise_detail(f)
                    )
                    
                # --- 1. Filtrar y Ordenar MIS TAREAS ---
                filtered_mine = [e for e in safe_my_exercises if state["filter_my_tasks"] in e.get("title", "").lower()]
                filtered_mine.sort(key=lambda x: x.get("title", "").lower(), reverse=(state["sort_my_tasks"] == "desc"))
                
                if not filtered_mine:
                    nuevas_mias.append(ft.Text("No hay tareas seleccionadas", color=COLORES["subtitulo"]))
                else:
                    for ex in filtered_mine:
                        nuevas_mias.append(create_exercise_card(ex, True))

                # --- 2. Filtrar y Ordenar GLOBALES ---
                filtered_global = [e for e in safe_available_exercises if state["filter_global_tasks"] in e.get("title", "").lower()]
                filtered_global.sort(key=lambda x: x.get("title", "").lower(), reverse=(state["sort_global_tasks"] == "desc"))

                if not filtered_global:
                    nuevas_disponibles.append(ft.Text("No hay tareas disponibles", color=COLORES["subtitulo"]))
                else:
                    for ex in filtered_global:
                        nuevas_disponibles.append(create_exercise_card(ex, False))
                    
                # ASIGNACIÓN ATÓMICA FINAL
                col_mine.controls = nuevas_mias
                col_available.controls = nuevas_disponibles
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
                                ft.Text("Catálogo local de tareas seleccionadas", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=refresh_exercises)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_tasks, sort_btn_my_tasks], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            col_mine
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(right=5)
                    ),
                    # COLUMNA DERECHA: CATÁLOGO GLOBAL
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Catálogo global de tareas disponibles", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=refresh_exercises)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_global_tasks, sort_btn_global_tasks], spacing=5),
                            ft.Divider(height=5, color="transparent"),
                            col_available
                        ], expand=True),
                        expand=1, 
                        bgcolor=COLORES["accento"], 
                        padding=10, 
                        border_radius=10,
                        margin=ft.margin.only(left=5)
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
            
            load_data_filtered()
            
        def update_dropdowns():
            with ui_lock:
                student_filter.options = [ft.dropdown.Option(key="Todos los estudiantes", text="Todos los estudiantes")] + [
                    ft.dropdown.Option(key=s["email"], text=f"{s.get('nombre', 'Estudiante')} ({s['email']})") for s in state["students"]
                ]
                exercise_filter.options = [ft.dropdown.Option("Todas las tareas")] + [
                    ft.dropdown.Option(key=e["filename"], text=e["title"]) for e in state["my_exercises"] if isinstance(e, dict)
                ]
                problem_filter.value = "Todos los ejercicios"
                problem_filter.disabled = True
                try:
                    profile_student_dropdown.options = [
                        ft.dropdown.Option(key=s["email"], text=f"{s.get('nombre', 'Estudiante')} ({s['email']})") for s in state["students"]
                    ]
                except Exception:
                    pass
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
            e.control.disabled = True
            page.update()
            
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
                
            e.control.disabled = False
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
            with ui_lock:
                nuevas_respuestas = []
                nuevos_chats = []
                raw_answers = data.get("respuestas", [])
                raw_chats = data.get("chats", [])
                target_prob = problem_filter.value
                
                # --- FILTRO CLIENT-SIDE DE PROBLEMA ---
                if target_prob and target_prob.isdigit():
                    pid = int(target_prob)
                    raw_answers = [r for r in raw_answers if r['problema_id'] == pid]
                    raw_chats = [c for c in raw_chats if c['problema_id'] == pid]
                
                for r in reversed(raw_answers):
                    nuevas_respuestas.append(ft.Container(content=ft.Column([
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

                    nuevos_chats.append(ft.Column([
                        ft.Text(f"{label} - P{c['problema_id']}", size=10, color=COLORES["subtitulo"]),
                        ft.Container(
                            content=ft.Text(c['content'], color=txt_color, size=13), 
                            bgcolor=bg, 
                            padding=10, 
                            border_radius=10,
                            width=None,
                        )
                    ], horizontal_alignment=align))
                
                if not nuevas_respuestas:
                    nuevas_respuestas.append(ft.Text("No hay respuestas registradas con estos filtros", italic=True, color=COLORES["subtitulo"]))
                if not nuevos_chats:
                    nuevos_chats.append(ft.Text("No hay historial de chat con estos filtros", italic=True, color=COLORES["subtitulo"]))
                    
                answers_col.controls = nuevas_respuestas
                chats_col.controls = nuevos_chats
                page.update()
            
        # =========================================
        # NAVEGACIÓN Y CARGA INICIAL
        # =========================================
        tab_monitor = ft.Container(
            content=ft.Column([
                # Fila Superior: Filtros
                ft.Container(
                    content=ft.Column([
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
                                ft.Text("Registro de Respuestas", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
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
                                ft.Text("Historial de Chat", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
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

        # Botón para descargar reporte (Oculto por defecto)
        download_live_report_btn = ft.ElevatedButton(
            "Descargar Reporte Excel", 
            icon=ft.Icons.DOWNLOAD,
            bgcolor=COLORES["primario"],
            color=COLORES["fondo"],
            height=40,
            visible=False
        )

        def toggle_session(e):
            nonlocal is_session_active
            is_session_active = not is_session_active
            
            if is_session_active:
                # ACTIVAR
                state["live_session_start"] = dt.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None).isoformat()
                download_live_report_btn.visible = False # Ocultar el botón anterior
                
                start_session_btn.text = "Detener Sesión"
                start_session_btn.icon = ft.Icons.STOP
                start_session_btn.bgcolor = COLORES["error"]
                session_status_text.value = "🔴 EN VIVO: Recibiendo alertas..."
                session_status_text.color = COLORES["error"]
                
                try:
                    if not sio.connected:
                        sio.connect(BASE) 
                except Exception as err:
                        flash(f"Error conectando: {err}", ok=False)
                        is_session_active = False
                        toggle_session(None) 
                        return
            else:
                # DESACTIVAR (El profesor terminó la clase)
                start_session_btn.text = "Iniciar Sesión en Vivo"
                start_session_btn.icon = ft.Icons.PLAY_ARROW
                start_session_btn.bgcolor = COLORES["exito"]
                session_status_text.value = "Sesión Inactiva"
                session_status_text.color = COLORES["subtitulo"]
                if sio.connected:
                    sio.disconnect()
                
                # GENERAR REPORTE AL DETENER
                if "live_session_start" in state:
                    session_end = dt.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None).isoformat()
                    flash("Procesando análisis cualitativo con IA... Un momento.", ok=True, ms=4000)
                    
                    def generar_reporte():
                        res = auth_request("POST", "/api/teacher/live-session/generate", json={
                            "start_time": state["live_session_start"],
                            "end_time": session_end
                        }, timeout=60)
                        
                        if res and res.status_code == 200:
                            report_id = res.json().get("report_id")
                            # Habilitar el botón de descarga
                            download_live_report_btn.visible = True
                            download_live_report_btn.on_click = lambda e: page.launch_url(f"{BASE}/api/teacher/live-session/download?token={state['token']}&report_id={report_id}")
                            flash("¡Análisis de sesión generado! Listo para descargar.", ok=True, ms=5000)
                        else:
                            try:
                                flash(res.json().get("error", "Error generando reporte"), ok=False)
                            except:
                                flash("No hubo datos suficientes para generar reporte", ok=False)
                        page.update()
                        
                    threading.Thread(target=generar_reporte, daemon=True).start()
                    del state["live_session_start"]
                    
            page.update()

        def load_full_dashboard():
            # Carga datos históricos iniciales
            reset_inactivity_timer()
            # Obtenemos lista de estudiantes para pintar las tarjetas iniciales
            render_dashboard_view(state["students"])
        
        def render_dashboard_view(student_list):
            with ui_lock:
                nuevas_tarjetas = []
                memoria_temporal = {}
                
                for email, datos in student_cards_state.items():
                    if 'latest_data' in datos:
                        memoria_temporal[email] = datos['latest_data']
                student_cards_state.clear()
                
                if not student_list:
                    nuevas_tarjetas.append(ft.Text("No hay estudiantes registrados", size=16))
                else:
                    for stu_obj in student_list:
                        stu_email = stu_obj["email"]
                        stu_name = stu_obj.get("nombre", "Estudiante")
                        datos_previos = memoria_temporal.get(stu_email)
                        
                        current_color = COLORES["borde"]
                        current_icon = ft.Icons.CIRCLE_OUTLINED
                        
                        if datos_previos:
                            status_color = datos_previos.get('status', 'green')
                            current_color = {
                                "green": COLORES["exito"], 
                                "yellow": COLORES["advertencia"], 
                                "red": COLORES["error"]
                            }.get(status_color, COLORES["borde"])
                            
                            current_icon = {
                                "green": ft.Icons.CHECK_CIRCLE,
                                "yellow": ft.Icons.WARNING,
                                "red": ft.Icons.ERROR
                            }.get(status_color, ft.Icons.CIRCLE)

                        progress_pct = datos_previos.get('progress_pct', 0.0) if datos_previos else 0.0
                        
                        if not datos_previos:
                            txt_val = "Esperando actividad..."
                        elif datos_previos.get('type') == 'answer':
                            txt_val = f"Entregó P{datos_previos.get('problem_id', '?')} ({(progress_pct*100):.0f}%)"
                        else:
                            txt_val = f"Conversando ({(progress_pct*100):.0f}%)"

                        bar_ctrl = ft.ProgressBar(value=progress_pct, color=COLORES["primario"], bgcolor=COLORES["borde"], height=6, border_radius=3)
                        txt_ctrl = ft.Text(txt_val, size=10, italic=True, color=COLORES["subtitulo"])
                        
                        card_content = ft.Column([
                                ft.Row([
                                    ft.Column([
                                        ft.Text(stu_name, weight="bold", size=16, no_wrap=True, color=COLORES["texto"]),
                                        ft.Text(stu_email, size=10, color=COLORES["subtitulo"], no_wrap=True),
                                    ], expand=True),
                                    ft.Icon(current_icon, color=current_color, size=24),
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                
                                ft.Divider(height=10, color="transparent"),
                                bar_ctrl,
                                txt_ctrl,
                                ft.Divider(height=5, color="transparent"),
                                
                                ft.ElevatedButton(
                                    "Ver Análisis", 
                                    icon=ft.Icons.VISIBILITY, 
                                    height=30, 
                                    style=ft.ButtonStyle(
                                        padding=5, 
                                        shape=ft.RoundedRectangleBorder(radius=5),
                                        color=COLORES.get("texto_boton", COLORES["texto"]),
                                        bgcolor=COLORES["boton"]
                                    ),
                                    on_click=lambda e, email=stu_email: show_student_detail(email)
                                )
                            ])

                        card = ft.Container(
                            content=card_content,
                            bgcolor=COLORES["fondo"],
                            padding=15,
                            border_radius=15,
                            shadow=ft.BoxShadow(blur_radius=10, color=COLORES["accento"]),
                            border=ft.border.all(2 if not datos_previos else 3, current_color), 
                            data=stu_email 
                        )
                        
                        student_cards_state[stu_email] = {
                            'control': card,
                            'bar_ctrl': bar_ctrl,
                            'txt_ctrl': txt_ctrl
                        }
                        
                        if datos_previos:
                            student_cards_state[stu_email]['latest_data'] = datos_previos
                        
                        nuevas_tarjetas.append(card)
                        
                dashboard_grid.controls = nuevas_tarjetas
                page.update()
        
        tab_dashboard = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("Dashboard en Tiempo Real", size=24, weight="bold", color=COLORES["primario"]),
                        session_status_text # Variable global definida arriba
                    ]),
                    ft.Row([
                        download_live_report_btn,
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

        # =========================================
        # PESTAÑA 3: Evaluaciones
        # =========================================
        state["pending_grades"] = []
        state["completed_grades"] = []
        state["filter_pending_grades"] = ""
        state["group_by_pending"] = "fecha"
        state["filter_completed_grades"] = ""
        state["group_by_completed"] = "fecha"
        
        search_completed_grades = ft.TextField(
            hint_text="Buscar por tarea, nombre o correo de estudiante...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_grade_filters("completed", e.control.value)
        )

        search_pending_grades = ft.TextField(
            hint_text="Buscar por tarea, nombre o correo de estudiante...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=True,
            on_change=lambda e: update_grade_filters("pending", e.control.value)
        )
        
        group_completed_dropdown = ft.Dropdown(
            label="Agrupar por",
            options=[
                ft.dropdown.Option("fecha", "Fecha"),
                ft.dropdown.Option("practica", "Tarea"),
                ft.dropdown.Option("problema", "Ejercicio"),
                ft.dropdown.Option("estudiante", "Estudiante"),
            ],
            value="fecha",
            width=180, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"],
            content_padding=10,
            on_change=lambda e: update_grade_grouping("completed", e.control.value)
        )

        group_pending_dropdown = ft.Dropdown(
            label="Agrupar por",
            options=[
                ft.dropdown.Option("fecha", "Fecha"),
                ft.dropdown.Option("practica", "Tarea"),
                ft.dropdown.Option("problema", "Ejercicio"),
                ft.dropdown.Option("estudiante", "Estudiante"),
            ],
            value="fecha",
            width=180, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"],
            content_padding=10,
            on_change=lambda e: update_grade_grouping("pending", e.control.value)
        )

        col_completed_grades = ft.ListView(expand=True, spacing=10)
        col_pending_grades = ft.ListView(expand=True, spacing=10)
        
        # --- DIÁLOGOS DE CALIFICACIÓN Y ELIMINACIÓN ---
        grade_llm_score_field = ft.TextField(
            label="Calificación Sugerida", 
            read_only=True, 
            text_align=ft.TextAlign.CENTER, 
            bgcolor=COLORES["borde"],
            expand=1
        )
        grade_score_field = ft.TextField(
            label="Calificación Asignada",
            text_align=ft.TextAlign.CENTER,
            expand=1
        )
        grade_comment_field = ft.TextField(
            label="Comentario",
            multiline=True,
            text_align=ft.TextAlign.JUSTIFY,
            min_lines=3,
            max_lines=6
        )
        grade_student_label = ft.Text(
            "",
            weight="bold",
            size=20,
            text_align=ft.TextAlign.CENTER
        ) 
        grade_task_label = ft.Text(
            "",
            size=14,
            text_align=ft.TextAlign.CENTER
        )
        grade_response_container = ft.Container(
            bgcolor=COLORES["fondo"], 
            padding=15, 
            border_radius=8, 
            width=float("inf")
        )
        btn_style = ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=20, vertical=15))
        grade_btn_cancel = ft.ElevatedButton("Regresar", bgcolor=COLORES["advertencia"], color=COLORES["texto"], style=btn_style, on_click=lambda e: close_grade_dlg())
        grade_btn_approve = ft.ElevatedButton("Aprobar Calificación Sugerida", bgcolor=COLORES["boton"], color=COLORES["texto"], style=btn_style)
        grade_btn_save = ft.ElevatedButton("Modificar Calificación", bgcolor=COLORES["exito"], color=COLORES["texto"], style=btn_style)
        
        grade_dlg = ft.AlertDialog(
            title=ft.Container(content=grade_student_label, alignment=ft.alignment.center),
            content=ft.Container(
                content=ft.Column([
                    ft.Container(content=grade_task_label, alignment=ft.alignment.center),
                    grade_response_container,
                    ft.Row([
                        grade_llm_score_field,
                        grade_score_field
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=20),
                    grade_comment_field,
                    ft.Row(
                        [grade_btn_cancel, grade_btn_approve, grade_btn_save], 
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        width=float("inf")
                    )
                ], tight=True, spacing=15),
                width=600
            ),
            scrollable=True
        )
        
        delete_eval_dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORES["error"]), ft.Text("Confirmar Eliminación")]),
            content=ft.Text("Estás a punto de eliminar definitivamente esta evaluación de la base de datos.\n\nEsto es útil si el estudiante reenvió la misma respuesta varias veces y quieres limpiar duplicados. ¿Deseas proceder?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: close_delete_eval_dlg()),
                ft.ElevatedButton("Eliminar Permanentemente", color=COLORES["fondo"], bgcolor=COLORES["error"], on_click=lambda e: confirm_delete_eval())
            ]
        )
        
        page.overlay.extend([grade_dlg, delete_eval_dlg])

        def close_grade_dlg():
            grade_dlg.open = False
            page.update()
            
        def open_delete_eval_dlg(eval_id):
            state["delete_target_id"] = eval_id
            delete_eval_dlg.open = True
            page.update()
            
        def close_delete_eval_dlg():
            delete_eval_dlg.open = False
            page.update()
            
        def confirm_delete_eval():
            eval_id = state.get("delete_target_id")
            if eval_id:
                res = auth_request("DELETE", f"/api/teacher/grades/{eval_id}")
                if res and res.status_code == 200:
                    flash("Evaluación eliminada correctamente de la base de datos.", ok=True)
                    load_grades()
                else:
                    flash("Error al eliminar la evaluación.", ok=False)
            close_delete_eval_dlg()

        def submit_grade(item_id, score, comment, action):
            grade_btn_approve.disabled = True
            grade_btn_save.disabled = True
            page.update()
            
            res = auth_request("POST", "/api/teacher/grades/submit", json={
                "id": item_id, "score": score, "comment": comment, "action": action
            })
            
            grade_btn_approve.disabled = False
            grade_btn_save.disabled = False
            
            if res and res.status_code == 200:
                flash("Evaluación guardada", ok=True)
                grade_dlg.open = False
                page.update()
                load_grades()
            else:
                flash("Error al guardar", ok=False)
                page.update()
                
        def open_grade_dialog(item, is_completed):
            grade_student_label.value = f"{item.get('nombre', item['correo'])}"
            date_str = item.get("fecha", "")[:10] if item.get("fecha") else "Sin fecha"
            grade_task_label.value = f"📚 {item['practica']} | 🔢 Ejercicio: {item['problema_id']} | 🕒 {date_str}"
            grade_response_container.content = ft.TextField(
                value=item['respuesta'],
                read_only=True,
                multiline=True,
                min_lines=3,
                max_lines=6,
                text_align=ft.TextAlign.JUSTIFY,
                border=ft.InputBorder.NONE,
                content_padding=0
            )
            llm_score_val = float(item.get('llm_score', 0))
            llm_score_display = int(llm_score_val) if llm_score_val.is_integer() else llm_score_val
            grade_llm_score_field.value = f"{llm_score_display}/10"
            
            if is_completed:
                teacher_score_val = float(item.get('teacher_score', item['llm_score']))
                teacher_score_display = int(teacher_score_val) if teacher_score_val.is_integer() else teacher_score_val
                grade_score_field.value = str(teacher_score_display)
                grade_comment_field.value = item.get('teacher_comment', item['llm_comment'])
            else:
                grade_score_field.value = "Pendiente"
                grade_comment_field.value = item['llm_comment']
                
            grade_btn_approve.on_click = lambda e: submit_grade(item['id'], item['llm_score'], grade_comment_field.value, "approve")
            
            def on_save_click(e):
                score_to_send = item['llm_score'] if grade_score_field.value == "Pendiente" else grade_score_field.value
                submit_grade(item['id'], score_to_send, grade_comment_field.value, "edit")
                
            grade_btn_save.on_click = on_save_click
            grade_dlg.open = True
            page.update()
            
        def update_grade_filters(target, value):
            if target == "completed": state["filter_completed_grades"] = value.lower()
            else: state["filter_pending_grades"] = value.lower()
            render_grades()

        def update_grade_grouping(target, value):
            if target == "completed": state["group_by_completed"] = value
            else: state["group_by_pending"] = value
            render_grades()

        def load_grades():
            res_pend = auth_request("GET", "/api/teacher/grades/pending")
            if res_pend and res_pend.status_code == 200:
                state["pending_grades"] = res_pend.json()
                
            res_comp = auth_request("GET", "/api/teacher/grades/completed")
            if res_comp and res_comp.status_code == 200:
                state["completed_grades"] = res_comp.json()
            
            render_grades()
            
        def refresh_grades(e):
            e.control.disabled = True
            page.update()
            load_grades()
            e.control.disabled = False
            page.update()
            
        def render_grades():
            with ui_lock:
                nuevas_completadas = []
                nuevas_pendientes = []
                
                def create_grade_card(item, is_completed):
                    score_to_show = item.get("teacher_score") if is_completed and item.get("teacher_score") is not None else item.get("llm_score", 0)
                    date_str = item.get("fecha", "")[:10] if item.get("fecha") else "Sin fecha"
                    
                    try:
                        score_val = float(score_to_show)
                    except (ValueError, TypeError):
                        score_val = 0.0
                        
                    if score_val < 6.0:
                        score_color = COLORES["error"]
                    elif score_val < 8.0:
                        score_color = COLORES["advertencia"]
                    else:
                        score_color = COLORES["exito"]
                    score_display = int(score_val) if score_val.is_integer() else score_val
                    
                    return ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(f"{item.get('nombre', 'Estudiante')}", weight="bold", size=14, color=COLORES["texto"]),
                                ft.Text(f"{item['correo']}", size=11, color=COLORES["subtitulo"]),
                                ft.Row([
                                    ft.Icon(ft.Icons.MENU_BOOK, size=12, color=COLORES["primario"]),
                                    ft.Text(f"{item['practica']} - P{item['problema_id']}", size=12, color=COLORES["primario"]),
                                    ft.Container(width=5),
                                    ft.Icon(ft.Icons.EVENT_NOTE, size=12, color=COLORES["subtitulo"]),
                                    ft.Text(f"{date_str}", size=12, color=COLORES["subtitulo"])
                                ], spacing=5)
                            ], expand=True),
                            ft.Column([
                                ft.Text(f"{score_display}/10", color=score_color, weight="bold", size=16),
                                ft.Text("Evaluación IA", size=10, italic=True) if not is_completed else ft.Text("Nota Final", size=10, italic=True)
                            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END),
                            ft.Column([
                                ft.IconButton(ft.Icons.EDIT, on_click=lambda e, i=item: open_grade_dialog(i, is_completed), icon_color=COLORES["primario"], tooltip="Editar Evaluación"),
                                ft.IconButton(ft.Icons.DELETE_FOREVER, on_click=lambda e, i=item: open_delete_eval_dlg(i['id']), icon_color=COLORES["error"], tooltip="Eliminar Duplicado")
                            ], spacing=0)
                        ]),
                        bgcolor=COLORES["fondo"], padding=10, border_radius=5, border=ft.border.all(1, COLORES["borde"]),
                        margin=ft.margin.only(bottom=5)
                    )

                def get_group_key(item, group_type):
                    if group_type == "fecha": return item.get("fecha", "")[:10]
                    elif group_type == "practica": return item.get("practica", "Sin práctica")
                    elif group_type == "problema": return f"Ejercicio #{item.get('problema_id', '?')}"
                    elif group_type == "estudiante": return item.get("nombre", item.get("correo"))
                    return "General"

                def build_grouped_list(items, group_by, is_completed):
                    items.sort(key=lambda x: (get_group_key(x, group_by), x.get("fecha", "")), reverse=True)
                    grupos = {}
                    for item in items:
                        g_key = get_group_key(item, group_by)
                        if g_key not in grupos:
                            grupos[g_key] = []
                        grupos[g_key].append(create_grade_card(item, is_completed))
                    controls = []
                    for g_key, card_list in grupos.items():
                        tile = ft.ExpansionTile(
                            title=ft.Text(f"{g_key}", weight="bold", color=COLORES["primario"]),
                            subtitle=ft.Text(f"Evaluaciones: {len(card_list)}", size=12, color=COLORES["subtitulo"]),
                            controls=card_list,
                            collapsed_text_color=COLORES["primario"],
                            text_color=COLORES["primario"],
                            initially_expanded=False,
                        )
                        controls.append(tile)
                    return controls

                # --- Filtrar Búsquedas ---
                filtered_comp = [g for g in state["completed_grades"] if state["filter_completed_grades"] in g.get("correo", "").lower() or state["filter_completed_grades"] in g.get("practica", "").lower() or state["filter_completed_grades"] in g.get("nombre", "").lower()]
                filtered_pend = [g for g in state["pending_grades"] if state["filter_pending_grades"] in g.get("correo", "").lower() or state["filter_pending_grades"] in g.get("practica", "").lower() or state["filter_pending_grades"] in g.get("nombre", "").lower()]

                if not filtered_comp: nuevas_completadas.append(ft.Text("No hay evaluaciones completadas", color=COLORES["subtitulo"]))
                else: nuevas_completadas.extend(build_grouped_list(filtered_comp, state["group_by_completed"], True))
                    
                if not filtered_pend: nuevas_pendientes.append(ft.Text("No hay evaluaciones pendientes", color=COLORES["subtitulo"]))
                else: nuevas_pendientes.extend(build_grouped_list(filtered_pend, state["group_by_pending"], False))
                
                col_completed_grades.controls = nuevas_completadas
                col_pending_grades.controls = nuevas_pendientes
                
                try:
                    col_completed_grades.update()
                    col_pending_grades.update()
                except Exception:
                    pass
                
        def download_grades_excel(e):
            # Obtener el filtro de búsqueda general si lo hay (puedes adaptarlo si decides poner dropdowns aquí)
            url = f"{BASE}/api/teacher/grades/download?token={state['token']}"
            page.launch_url(url)

        btn_download_excel = ft.ElevatedButton(
            "Descargar Reporte Excel",
            icon=ft.Icons.TABLE_VIEW,
            bgcolor=COLORES["primario"],
            color=COLORES["fondo"],
            on_click=download_grades_excel
        )
        
        tab_grading = ft.Container(
            content=ft.Column([
                ft.Row([
                     ft.Text("Administración de Calificaciones", size=20, weight="bold", color=COLORES["primario"], expand=True),
                     btn_download_excel
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                
                ft.Divider(color=COLORES["borde"]),
                
                ft.Row([
                    # COLUMNA IZQUIERDA: Completadas
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Evaluaciones Completadas", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=refresh_grades)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_completed_grades, group_completed_dropdown], spacing=10),
                            ft.Divider(height=5, color="transparent"),
                            col_completed_grades
                        ], expand=True),
                        expand=1,
                        bgcolor=COLORES["accento"],
                        padding=10,
                        border_radius=10,
                        margin=ft.margin.only(right=5)
                    ),
                    # COLUMNA DERECHA: Pendientes
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Evaluaciones Pendientes", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Recargar", on_click=refresh_grades)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_pending_grades, group_pending_dropdown], spacing=10),
                            ft.Divider(height=5, color="transparent"),
                            col_pending_grades
                        ], expand=True),
                        expand=1,
                        bgcolor=COLORES["accento"],
                        padding=10,
                        border_radius=10,
                        margin=ft.margin.only(left=5)
                    )
                ], expand=True)
            ], expand=True), 
            padding=20
        )
        
        # =========================================
        # PESTAÑA: Perfil Alumno
        # =========================================
        
        # 1. El Buscador (¡Ahora sí en su propia pestaña!)
        profile_student_dropdown = ft.Dropdown(
            label="Selecciona un estudiante",
            options=[],
            width=400,
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            on_change=lambda e: load_student_profile(e.control.value)
        )
        
        profile_content = ft.ListView(expand=True, spacing=15, padding=ft.padding.only(right=20))
        
        def load_student_profile(email):
            if not email: return
            profile_content.controls = [
                ft.Container(content=ft.ProgressRing(color=COLORES["primario"]), alignment=ft.alignment.center, height=100)
            ]
            page.update()
            
            def fetch():
                res = auth_request("GET", f"/api/teacher/student-profile/{email}")
                if res and res.status_code == 200:
                    render_student_profile(res.json(), email)
                else:
                    profile_content.controls = [ft.Text("Error al cargar perfil", color=COLORES["error"])]
                    page.update()
            threading.Thread(target=fetch, daemon=True).start()
            
        def generate_report_for_practice(email, prac_name):
            flash(f"Analizando interacciones con IA para {prac_name}... esto tomará unos segundos...", ok=True, ms=6000)
            def fetch():
                res = auth_request("POST", "/api/teacher/generate-report", json={"student_email": email, "practice_name": prac_name}, timeout=60)
                if res and res.status_code == 200:
                    flash("¡Reporte cualitativo generado con éxito!", ok=True)
                    load_student_profile(email) # Recargar la vista para mostrarlo
                else:
                    flash("Error al generar el reporte con la IA.", ok=False)
            threading.Thread(target=fetch, daemon=True).start()
            
        def render_student_profile(data, email):
            with ui_lock:
                nuevos_controles_perfil = []
                if not data:
                    nuevos_controles_perfil.append(ft.Text("El estudiante aún no cuenta con actividad registrada", italic=True, color=COLORES["subtitulo"]))
                else:
                    for prac_name, prac_data in data.items():
                        problemas = prac_data.get("problemas", {})
                        
                        prob_controls = []
                        # --- UI DEL REPORTE DE INTELIGENCIA ARTIFICIAL ---
                        reporte = prac_data.get("reporte")
                        if reporte:
                            reporte_ui = ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        ft.Icon(ft.Icons.AUTO_AWESOME, color=COLORES["advertencia"]),
                                        ft.Text("Diagnóstico Cualitativo de la IA", weight="bold", size=16, color=COLORES["primario"]),
                                        ft.IconButton(ft.Icons.REFRESH, tooltip="Regenerar Reporte", icon_color=COLORES["subtitulo"], on_click=lambda e, pr=prac_name: generate_report_for_practice(email, pr))
                                    ]),
                                    ft.Row([
                                        ft.Container(
                                            content=ft.Column([ft.Text("Perfil de Aprendizaje", size=11, color=COLORES["subtitulo"]), ft.Text(reporte["perfil_estudiante"], weight="bold", color=COLORES["texto"])]),
                                            bgcolor=COLORES["fondo"], padding=10, border_radius=5, expand=1, border=ft.border.all(1, COLORES["borde"])
                                        ),
                                        ft.Container(
                                            content=ft.Column([ft.Text("Nivel de Persistencia", size=11, color=COLORES["subtitulo"]), ft.Text(reporte["persistencia"], weight="bold", color=COLORES["texto"])]),
                                            bgcolor=COLORES["fondo"], padding=10, border_radius=5, expand=1, border=ft.border.all(1, COLORES["borde"])
                                        )
                                    ]),
                                    ft.Text("Análisis Pedagógico:", weight="bold", size=12, color=COLORES["subtitulo"]),
                                    ft.Text(reporte["diagnostico_general"], size=13, color=COLORES["texto"], text_align=ft.TextAlign.JUSTIFY)
                                ], spacing=10),
                                bgcolor=COLORES["accento"],
                                border=ft.border.all(1, COLORES["advertencia"]),
                                border_radius=8,
                                padding=15,
                                margin=ft.margin.only(bottom=15, right=15)
                            )
                        else:
                            reporte_ui = ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.INSIGHTS, color=COLORES["primario"]),
                                    ft.Text("Aún no se ha generado un reporte de desempeño para esta sesión.", expand=True, color=COLORES["subtitulo"], italic=True),
                                    ft.ElevatedButton("Generar Reporte con IA", icon=ft.Icons.AUTO_AWESOME, bgcolor=COLORES["boton"], color=COLORES["texto"], on_click=lambda e, pr=prac_name: generate_report_for_practice(email, pr))
                                ]),
                                bgcolor=COLORES["fondo"], padding=15, border_radius=8, border=ft.border.all(1, COLORES["borde"]), margin=ft.margin.only(bottom=15, right=15)
                            )
                        # Insertar el reporte hasta arriba de la lista de ejercicios
                        prob_controls.append(reporte_ui)
                        for pid, pdata in sorted(problemas.items(), key=lambda x: int(x[0])):
                            ans = pdata.get("respuesta")
                            chats = pdata.get("chats", [])
                            
                            # UI de Calificación
                            score_ui = ft.Container()
                            if ans:
                                final_score = ans.get("teacher_score") if ans.get("teacher_score") is not None else ans.get("llm_score", 0.0)
                                status_str = "Evaluado por Profesor" if ans.get("teacher_score") is not None else ("Evaluado por IA" if ans.get("status") == "pending" else "Evaluado")
                                border_color = COLORES["exito"] if ans.get("status") in ["approved", "edited"] else COLORES["advertencia"]
                                
                                score_ui = ft.Container(
                                    content=ft.Column([
                                        ft.Text(f"Calificación: {final_score}/10", weight="bold", color=COLORES["primario"]),
                                        ft.Text(f"Estado: {status_str}", size=11, color=COLORES["subtitulo"]),
                                        ft.Text(f"Comentario: {ans.get('teacher_comment') or ans.get('llm_comment') or 'Sin comentarios'}", size=12, italic=True, color=COLORES["texto"])
                                    ], spacing=2),
                                    bgcolor=COLORES["accento"], padding=10, border_radius=5, border=ft.border.all(1, border_color)
                                )
                            else:
                                score_ui = ft.Text("Pregunta no respondida aún.", italic=True, color=COLORES["advertencia"])

                            # UI de Historial de Chat
                            chat_ui_controls = []
                            if chats:
                                for c in chats:
                                    role = c.get("role", "user")
                                    bg = COLORES["secundario"] if role == "user" else (COLORES["primario"] if role == "teacher" else COLORES["borde"])
                                    tc = COLORES["fondo"] if role in ["user", "teacher"] else COLORES["texto"]
                                    align = ft.CrossAxisAlignment.END if role == "user" else ft.CrossAxisAlignment.START
                                    who = "Estudiante" if role == "user" else ("Profesor" if role=="teacher" else "Tutor IA")
                                    
                                    chat_ui_controls.append(
                                        ft.Column([
                                            ft.Text(f"{who} - {c['fecha'][:16].replace('T', ' ')}", size=10, color=COLORES["subtitulo"]),
                                            ft.Container(content=ft.Text(c["content"], color=tc, size=13), bgcolor=bg, padding=10, border_radius=8)
                                        ], horizontal_alignment=align, spacing=2)
                                    )
                            
                            chat_scroll = ft.Column(chat_ui_controls, spacing=10, scroll=ft.ScrollMode.AUTO)
                            chat_container = ft.Container(
                                content=chat_scroll,
                                height=250, padding=10, bgcolor=COLORES["fondo"], 
                                border=ft.border.all(1, COLORES["borde"]), border_radius=5,
                            ) if chats else ft.Text("No hay interacciones de chat en este problema.", size=12, color=COLORES["subtitulo"])

                            # Ensamblar la Tarjeta del Problema
                            prob_card = ft.Container(
                                content=ft.Column([
                                    ft.Text(f"Problema {pid}", weight="bold", size=16, color=COLORES["secundario"]),
                                    ft.Divider(height=2, color="transparent"),
                                    ft.Row([
                                        ft.Column([
                                            ft.Text("Evaluación General:", weight="bold", size=12, color=COLORES["texto"]),
                                            score_ui,
                                            ft.Text("Respuesta Entregada:", weight="bold", size=12, color=COLORES["texto"]) if ans else ft.Container(),
                                            ft.Text(ans["texto"], size=13, color=COLORES["texto"], selectable=True) if ans and ans.get("texto") else ft.Container(),
                                        ], expand=1),
                                        
                                        ft.Column([
                                            ft.Text("Historial de Conversación:", weight="bold", size=12, color=COLORES["texto"]),
                                            chat_container
                                        ], expand=1)
                                    ], vertical_alignment=ft.CrossAxisAlignment.START)
                                ], spacing=5),
                                padding=15, border=ft.border.all(1, COLORES["borde"]), border_radius=8, bgcolor=COLORES["fondo"],
                                margin=ft.margin.only(bottom=10, right=15)
                            )
                            prob_controls.append(prob_card)

                        # Acordeón de la Práctica
                        prac_tile = ft.ExpansionTile(
                            title=ft.Text(f"Práctica: {prac_name}", weight="bold", color=COLORES["primario"]),
                            subtitle=ft.Text(f"Ejercicios con actividad: {len(problemas)}", size=12, color=COLORES["subtitulo"]),
                            controls=prob_controls,
                            collapsed_text_color=COLORES["primario"],
                            text_color=COLORES["primario"],
                            initially_expanded=False,
                        )
                        nuevos_controles_perfil.append(prac_tile)
                        
                profile_content.controls = nuevos_controles_perfil
                profile_content.update()
                
        tab_profile = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.PERSON_SEARCH, size=30, color=COLORES["primario"]),
                    ft.Column([
                        ft.Text("Expediente del Alumno", size=20, weight="bold", color=COLORES["primario"]),
                        ft.Text("Selecciona un estudiante para revisar todas sus entregas, calificaciones y conversaciones", color=COLORES["subtitulo"], size=12)
                    ])
                ]),
                ft.Divider(color=COLORES["borde"]),
                profile_student_dropdown,
                ft.Divider(color="transparent", height=10),
                ft.Container(content=profile_content, expand=True, bgcolor=COLORES["accento"], padding=15, border_radius=10)
            ], expand=True),
            padding=20,
            expand=True
        )
        
        # Tabs Principales
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            on_change=lambda e: (
                reset_inactivity_timer(),
                load_exercises() if e.control.selected_index == 1 else None,
                load_grades() if e.control.selected_index == 2 else None,
                load_full_dashboard() if e.control.selected_index == 5 else None
            ),
            tabs=[
                ft.Tab(text="Estudiantes", icon=ft.Icons.GROUPS, content=tab_students),
                ft.Tab(text="Tareas", icon=ft.Icons.ASSIGNMENT, content=tab_exercises),
                ft.Tab(text="Evaluaciones", icon=ft.Icons.GRADE, content=tab_grading),
                ft.Tab(text="Monitoreo", icon=ft.Icons.INSIGHTS, content=tab_monitor),
                ft.Tab(text="Perfil Alumno", icon=ft.Icons.PERSON_SEARCH, content=tab_profile),
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
                        on_click=lambda e: (page.client_storage.remove("teacher_token"), state.update({"token": None}), show_login())
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
        load_grades()

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
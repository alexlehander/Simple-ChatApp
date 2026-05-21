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
        "classes": [],
        "filter_students_class": "Todas las clases",
        "filter_tasks_class": "Todas las clases",
    }
    
    def on_disconnect(e):
        page.is_alive = False
        print("Cliente desconectado, deteniendo hilos")
        
    def load_k(page, k, default=None):
        try:
            if page.client_storage.contains_key(k):
                return page.client_storage.get(k)
        except Exception:
            pass
        return default
        
    def save_k(page, k, v):
        try:
            page.client_storage.set(k, v)
        except Exception:
            pass
            
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
    is_session_active = load_k(page, "is_live_session_active", False)
    if is_session_active:
        state["live_session_start"] = load_k(page, "live_session_start_time")
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
        if detail_dlg in page.overlay:
            page.overlay.remove(detail_dlg)
        page.update()

    def show_student_detail(email):
        detail_dlg_title.value = f"Línea de Tiempo: {email.split('@')[0]}"
        filter_recent = {"value": True} 
        alert_msg_field = ft.TextField(label="Mensaje urgente", multiline=True, min_lines=2, expand=True)
        
        def send_alert_action(e):
            if not alert_msg_field.value.strip():
                flash("El mensaje no puede estar vacío", ok=False)
                return
            e.control.disabled = True
            page.update()
            res = auth_request("POST", "/api/teacher/send-alert", json={"student_email": email, "message": alert_msg_field.value})
            if res and res.status_code == 200:
                flash("Alerta enviada", ok=True)
                alert_dlg.open = False
                alert_msg_field.value = ""
            else:
                flash("Error al enviar alerta", ok=False)
            e.control.disabled = False
            page.update()

        alert_dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORES["advertencia"]), ft.Text("Enviar Alerta")]),
            content=ft.Container(content=alert_msg_field, width=400, height=100),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: (setattr(alert_dlg, 'open', False), page.overlay.remove(alert_dlg) if alert_dlg in page.overlay else None, page.update())),
                ft.ElevatedButton("Enviar", bgcolor=COLORES["error"], color=COLORES["fondo"], on_click=send_alert_action)
            ]
        )
        if alert_dlg not in page.overlay: page.overlay.append(alert_dlg)

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
            import datetime as dt_module
            now_tj = dt_module.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None)

            filtered_data = []
            for event in timeline_data:
                try:
                    dt_obj = dt_module.datetime.fromisoformat(event['timestamp'].replace('Z', ''))
                    if filter_recent["value"]:
                        if (now_tj - dt_obj).total_seconds() > 7200: continue
                    filtered_data.append((event, dt_obj))
                except Exception:
                    filtered_data.append((event, None))

            if not filtered_data:
                nuevos_controles.append(ft.Container(content=ft.Text("Sin interacciones recientes.", italic=True), alignment=ft.alignment.center, padding=20))
            else:
                for event, dt_obj in filtered_data:
                    time_str = dt_obj.strftime("%I:%M %p") if dt_obj else "??"
                    icon_shape, icon_color = get_status_meta(event['color'])
                    event_icon = ft.Icons.CHAT_BUBBLE_OUTLINED if event['type'] == 'chat' else ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED
                    detalle_texto = event.get('content') or event.get('respuesta') or event.get('texto') or "Sin detalle adicional."
                    
                    item_tile = ft.ExpansionTile(
                        title=ft.Row([
                            ft.Column([
                                ft.Text(time_str, size=10, color=COLORES["subtitulo"]),
                                ft.Icon(event_icon, color=COLORES["primario"], size=18),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
                            ft.VerticalDivider(width=10),
                            ft.Column([
                                ft.Text(event['description'], weight="bold", size=13, color=COLORES["texto"]),
                                ft.Text(f"Tipo: {event['type'].title()}", size=10, color=COLORES["subtitulo"]),
                            ], expand=True, spacing=0),
                            ft.Icon(icon_shape, color=icon_color, size=20)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
                        controls=[
                            ft.Container(
                                content=ft.Column([
                                    ft.Divider(height=1, color=COLORES["borde"]),
                                    ft.Text("Contenido de la interacción:", size=11, weight="bold", color=COLORES["primario"]),
                                    ft.Text(detalle_texto, size=12, color=COLORES["texto"]),
                                ], spacing=5),
                                padding=ft.padding.only(left=40, right=20, bottom=15, top=5),
                                bgcolor=COLORES["accento"]
                            )
                        ],
                        collapsed_bgcolor=COLORES["fondo"],
                        bgcolor=COLORES["fondo"],
                        shape=ft.Border(),
                    )
                    nuevos_controles.append(item_tile)
            detail_dlg_content.controls = nuevos_controles
            try:
                if detail_dlg_content.page:
                    detail_dlg_content.update()
            except Exception:
                pass
                
        def trigger_load(e=None):
            detail_dlg_content.controls = [ft.Container(content=ft.ProgressRing(), alignment=ft.alignment.center, height=100)]
            try:
                if detail_dlg_content.page:
                    detail_dlg_content.update()
            except Exception:
                pass
            threading.Thread(target=fetch_and_render_timeline, daemon=True).start()

        def on_switch_change(e):
            filter_recent["value"] = e.control.value
            trigger_load()

        filter_switch = ft.Switch(label="Últimas 2h", value=True, on_change=on_switch_change, active_color=COLORES["primario"])
        btn_alert = ft.IconButton(ft.Icons.ADD_ALERT, icon_color=COLORES["error"], on_click=lambda e: setattr(alert_dlg, 'open', True) or page.update())

        detail_dlg.title = ft.Row([detail_dlg_title, ft.Row([filter_switch, btn_alert])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        detail_dlg.content.width = 700
        detail_dlg.open = True
        page.update()
        trigger_load()
        
    @sio.event
    def connect():
        print("✅ Conectado al servidor de tiempo real")
    
    @sio.event
    def disconnect():
        print("❌ Desconectado del servidor de tiempo real")
        def _reconnect_loop():
            import time as _t
            for attempt in range(1, 6):
                _t.sleep(3 * attempt)
                if not page.is_alive:
                    return
                if not load_k(page, "is_live_session_active", False):
                    return
                try:
                    if not sio.connected:
                        sio.connect(BASE)
                        print(f"✅ Reconectado al servidor (intento {attempt})")
                        session_status_text.value = "🔴 EN VIVO: Recibiendo alertas..."
                        session_status_text.color = COLORES["error"]
                        try:
                            session_status_text.update()
                        except Exception:
                            pass
                        return
                except Exception as e:
                    print(f"⚠️ Reintento {attempt}/5 fallido: {e}")
            if page.is_alive:
                session_status_text.value = "⚠️ Conexión perdida. Recarga la página."
                session_status_text.color = COLORES["advertencia"]
                try:
                    session_status_text.update()
                    flash("Conexión en tiempo real perdida. Intenta recargar.", ok=False, ms=8000)
                except Exception:
                    pass
        threading.Thread(target=_reconnect_loop, daemon=True).start()
    
    @sio.event
    def student_activity(data):
        """Handles real-time updates from backend servers."""
        if not load_k(page, "is_live_session_active", False): return
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
            if method == "PUT": return requests.put(url, **kwargs)
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
                if load_k(page, "is_live_session_active", False):
                    reset_inactivity_timer()
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
        
        filter_students_class_dropdown = ft.Dropdown(
            label="Filtrar por Clase",
            options=[ft.dropdown.Option("Todas las clases")],
            value="Todas las clases",
            expand=1,
            text_size=12,
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            content_padding=10,
            on_change=lambda e: update_filter_class("students", e.control.value)
        )
        
        filter_tasks_class_dropdown = ft.Dropdown(
            label="Filtrar por Clase",
            options=[ft.dropdown.Option("Todas las clases")],
            value="Todas las clases",
            expand=1,
            text_size=12,
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            content_padding=10,
            on_change=lambda e: update_filter_class("tasks", e.control.value)
        )
        
        # ==========================================
        # FILE PICKER: SUBIDA DE PDF A LA IA
        # ==========================================
        def on_upload_result(e: ft.FilePickerResultEvent):
            if e.files:
                page.splash = ft.ProgressBar()
                page.update()
                filename = e.files[0].name
                upload_url = (
                    f"{BASE}/api/teacher/exercises/upload"
                    f"?jwt={state['token']}&filename={filename}"
                )
                file_picker.upload([
                    ft.FilePickerUploadFile(
                        filename,
                        upload_url=upload_url,
                        method="POST"
                    )
                ])
                
        # ==========================================
        # FILE PICKER: SUBIDA DE PDF A LA IA
        # ==========================================
        state["_pdf_pending_filename"] = None
        
        def on_upload_result(e: ft.FilePickerResultEvent):
            if not e.files:
                return
            state["_pdf_pending_filename"] = e.files[0].name
            _open_pdf_params_dialog()
            
        def _open_pdf_params_dialog():
            f_nombre = ft.TextField(
                label="Nombre de la práctica",
                hint_text="Dejar vacío → la IA lo sugiere",
                expand=True,
                border_color=COLORES["primario"],
                color=COLORES["texto"],
                bgcolor=COLORES["fondo"],
                focused_border_color=COLORES["secundario"],
                text_size=13,
            )
            f_tiempo = ft.TextField(
                label="Tiempo límite (minutos)",
                hint_text="Vacío = sin límite",
                width=200,
                keyboard_type=ft.KeyboardType.NUMBER,
                border_color=COLORES["primario"],
                color=COLORES["texto"],
                bgcolor=COLORES["fondo"],
                focused_border_color=COLORES["secundario"],
                text_size=13,
            )
            f_descripcion = ft.TextField(
                label="Descripción para los estudiantes",
                hint_text="Vacío → la IA la genera",
                multiline=True,
                min_lines=2,
                max_lines=4,
                expand=True,
                border_color=COLORES["primario"],
                color=COLORES["texto"],
                bgcolor=COLORES["fondo"],
                focused_border_color=COLORES["secundario"],
                text_size=13,
            )
            f_rubricas = ft.TextField( 
                label="Rúbricas de evaluación (separadas por coma)",
                hint_text='Ej: "Exactitud, Procedimiento, Explicación"   |   Vacío = sin rúbricas',
                multiline=True,
                min_lines=2,
                max_lines=3,
                expand=True,
                border_color=COLORES["primario"],
                color=COLORES["texto"],
                bgcolor=COLORES["fondo"],
                focused_border_color=COLORES["secundario"],
                text_size=13,
            )
            f_num_ej = ft.TextField(
                label="Número de ejercicios",
                hint_text="Vacío → la IA decide",
                width=200,
                keyboard_type=ft.KeyboardType.NUMBER,
                border_color=COLORES["primario"],
                color=COLORES["texto"],
                bgcolor=COLORES["fondo"],
                focused_border_color=COLORES["secundario"],
                text_size=13,
            )
            lbl_error = ft.Text(
                "",
                color=COLORES["error"],
                size=12,
                visible=False,
            )

            def _do_upload(ev):
                tiempo_str = (f_tiempo.value or "").strip()
                if tiempo_str:
                    if not tiempo_str.isdigit() or not (5 <= int(tiempo_str) <= 480):
                        lbl_error.value = "El tiempo debe ser un número entre 5 y 480 minutos, o dejar vacío."
                        lbl_error.visible = True
                        page.update()
                        return
                num_str = (f_num_ej.value or "").strip()
                if num_str:
                    if not num_str.isdigit() or not (1 <= int(num_str) <= 30):
                        lbl_error.value = "El número de ejercicios debe ser un entero entre 1 y 30, o dejar vacío."
                        lbl_error.visible = True
                        page.update()
                        return
                params_dlg.open = False
                page.update()
                import urllib.parse
                qs = urllib.parse.urlencode({
                    "jwt":           state["token"],
                    "filename":      state["_pdf_pending_filename"],
                    "p_nombre":      (f_nombre.value or "").strip(),
                    "p_tiempo":      tiempo_str,
                    "p_descripcion": (f_descripcion.value or "").strip(),
                    "p_rubricas":    (f_rubricas.value or "").strip(),
                    "p_num_ej":      num_str,
                })
                upload_url = f"{BASE}/api/teacher/exercises/upload?{qs}"
                page.splash = ft.ProgressBar()
                page.update()
                file_picker.upload([
                    ft.FilePickerUploadFile(
                        state["_pdf_pending_filename"],
                        upload_url=upload_url,
                        method="POST",
                    )
                ])
                
            params_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.AUTO_AWESOME, color=COLORES["primario"], size=22),
                    ft.Text(
                        "Configurar tarea generada por IA",
                        weight="bold",
                        color=COLORES["texto"],
                        size=17,
                    ),
                ], spacing=8),
                content=ft.Container(
                    width=580,
                    content=ft.Column(
                        [
                            ft.Text(
                                f"📄  {state['_pdf_pending_filename']}",
                                color=COLORES["subtitulo"],
                                size=12,
                                italic=True,
                            ),
                            ft.Text(
                                "Completa los campos que quieras personalizar. "
                                "Los que dejes vacíos serán decididos por la IA.",
                                color=COLORES["subtitulo"],
                                size=12,
                            ),
                            ft.Divider(color=COLORES["borde"]),
                            ft.Row([f_nombre, f_tiempo], spacing=10),
                            f_descripcion,
                            f_rubricas,
                            ft.Row([
                                f_num_ej,
                                ft.Text(
                                    "máx. recomendado: 10",
                                    size=11,
                                    color=COLORES["subtitulo"],
                                    italic=True,
                                ),
                            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            lbl_error,
                        ],
                        spacing=10,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    padding=ft.padding.only(top=6, bottom=2),
                ),
                actions=[
                    ft.TextButton(
                        "Cancelar",
                        on_click=lambda _: (
                            setattr(params_dlg, "open", False),
                            page.overlay.remove(params_dlg) if params_dlg in page.overlay else None,
                            page.update(),
                        ),
                    ),
                    ft.ElevatedButton(
                        "Procesar con IA  →",
                        icon=ft.Icons.ROCKET_LAUNCH,
                        bgcolor=COLORES["primario"],
                        color=COLORES["fondo"],
                        on_click=_do_upload,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            if params_dlg not in page.overlay:
                page.overlay.append(params_dlg)
            params_dlg.open = True
            page.update()

        def on_upload_progress(e: ft.FilePickerUploadEvent):
            if e.error:
                page.splash = None
                flash(f"Error al subir: {e.error}", ok=False)
                page.update()
                return

            if e.progress == 1.0:
                page.splash = ft.ProgressBar(color=COLORES["advertencia"])
                flash("Archivo en el servidor. La IA lo está leyendo, espera por favor...", ok=True, ms=4000)
                page.update()

                def check_backend_success():
                    old_count = len(state.get("my_exercises", []))
                    for _ in range(60):
                        time.sleep(5)
                        try:
                            res = auth_request("GET", "/api/teacher/my-exercises")
                            if res and res.status_code == 200:
                                current_exercises = res.json()
                                if len(current_exercises) > old_count:
                                    state["my_exercises"] = current_exercises
                                    page.splash = None
                                    flash("✅ ¡PDF procesado! Tarea generada correctamente.", ok=True, ms=5000)
                                    load_exercises()
                                    return
                        except Exception:
                            pass
                    page.splash = None
                    flash("❌ Tiempo de espera agotado o error al procesar el PDF.", ok=False, ms=6000)
                    page.update()
                threading.Thread(target=check_backend_success, daemon=True).start()
        file_picker = ft.FilePicker(on_result=on_upload_result, on_upload=on_upload_progress)
        page.overlay.append(file_picker)
        
        def update_filter_class(target, value):
            if target == "students": state["filter_students_class"] = value
            else: state["filter_tasks_class"] = value
            render_students() if target == "students" else render_exercises()
        
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
            try:
                res_my = auth_request("GET", "/api/teacher/students")
                if res_my and res_my.status_code == 200:
                    state["students"] = res_my.json()
                elif res_my and res_my.status_code == 401:
                    flash("Sesión expirada. Por favor inicia sesión de nuevo.", ok=False)
                    return
                res_all = auth_request("GET", "/api/teacher/all-users")
                if res_all and res_all.status_code == 200:
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
                if state["filter_students_class"] != "Todas las clases":
                    clase_actual = next((c for c in state["classes"] if c["nombre"] == state["filter_students_class"]), None)
                    if clase_actual:
                        emails_clase = {est["email"] for est in clase_actual["estudiantes"]}
                        mis_filtrados = [s for s in mis_filtrados if s["email"] in emails_clase]
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
                try:
                    my_students_col.update()
                    global_students_col.update()
                except Exception:
                    pass
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
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_students)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_students, filter_students_class_dropdown, sort_btn_my], spacing=5),
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
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_students)
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
        
        if ex_detail_dlg not in page.overlay: 
            page.overlay.append(ex_detail_dlg)
        
        def close_ex_detail_dlg():
            ex_detail_dlg.open = False
            if ex_detail_dlg in page.overlay:
                page.overlay.remove(ex_detail_dlg)
            page.update()
            
        def open_exercise_dialog(ex):
            is_mine = ex.get("is_mine", False)
            ex_id = ex["practica_id"]
            
            res = auth_request("GET", f"/api/exercises/detail/{ex_id}")
            if not res or res.status_code != 200:
                flash("Error al cargar la tarea", ok=False)
                return
                
            data = res.json()
            
            if is_mine:
                # --- MODO EDICIÓN (Tus tareas) ---
                title_field = ft.TextField(label="Título de la Práctica", value=data.get("title", ""), expand=True)
                desc_field = ft.TextField(label="Descripción general", value=data.get("description", ""), multiline=True, min_lines=2)
                time_field = ft.TextField(label="Tiempo (min)", value=str(int(data.get("max_time", 3600)/60)), width=120)
                
                rubricas_list = data.get("rubricas", [])
                problemas_list = data.get("problemas", [])
                
                col_rubricas = ft.Column(spacing=5, scroll="auto", height=150)
                def render_r():
                    col_rubricas.controls.clear()
                    for i, r in enumerate(rubricas_list):
                        dim_tf = ft.TextField(label="Dimensión", value=r.get("dimension",""), expand=1, text_size=12, on_change=lambda e, idx=i: r.update({"dimension": e.control.value}))
                        desc_tf = ft.TextField(label="Descripción", value=r.get("descripcion",""), expand=2, text_size=12, on_change=lambda e, idx=i: r.update({"descripcion": e.control.value}))
                        del_btn = ft.IconButton(ft.Icons.DELETE, icon_color=COLORES["error"], on_click=lambda e, idx=i: delete_r(idx))
                        col_rubricas.controls.append(ft.Row([dim_tf, desc_tf, del_btn]))
                    page.update()
                
                def delete_r(idx):
                    rubricas_list.pop(idx)
                    render_r()
                    
                def add_r(e):
                    rubricas_list.append({"dimension": "", "descripcion": ""})
                    render_r()
                    
                render_r()
                
                col_problemas = ft.Column(spacing=5, scroll="auto", height=200)
                def render_p():
                    col_problemas.controls.clear()
                    for i, p in enumerate(problemas_list):
                        enun_tf = ft.TextField(label=f"Problema {i+1}", value=p.get("enunciado",""), expand=True, multiline=True, text_size=12, on_change=lambda e, idx=i: p.update({"enunciado": e.control.value, "id": idx+1}))
                        del_btn = ft.IconButton(ft.Icons.DELETE, icon_color=COLORES["error"], on_click=lambda e, idx=i: delete_p(idx))
                        col_problemas.controls.append(ft.Row([enun_tf, del_btn]))
                    page.update()
                
                def delete_p(idx):
                    problemas_list.pop(idx)
                    render_p()
                    
                def add_p(e):
                    problemas_list.append({"id": len(problemas_list)+1, "enunciado": ""})
                    render_p()
                    
                render_p()

                def save_task(e):
                    e.control.disabled = True
                    page.update()
                    payload = {
                        "title": title_field.value,
                        "description": desc_field.value,
                        "max_time": int(time_field.value) if time_field.value.isdigit() else 60,
                        "rubricas": rubricas_list,
                        "problemas": problemas_list
                    }
                    res = auth_request("PUT", f"/api/teacher/exercises/{ex_id}", json=payload)
                    if res and res.status_code == 200:
                        flash("Tarea actualizada exitosamente", ok=True)
                        dlg.open = False
                        load_exercises()
                    else:
                        flash("Error al guardar", ok=False)
                        e.control.disabled = False
                    page.update()

                content = ft.Column([
                    ft.Row([title_field, time_field]),
                    desc_field,
                    ft.Divider(),
                    ft.Row([ft.Text("Rúbricas de Evaluación", weight="bold", color=COLORES["primario"]), ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=COLORES["exito"], on_click=add_r)], alignment="spaceBetween"),
                    ft.Container(content=col_rubricas, padding=10, border=ft.border.all(1, COLORES["borde"]), border_radius=5),
                    ft.Divider(),
                    ft.Row([ft.Text("Ejercicios / Problemas", weight="bold", color=COLORES["primario"]), ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=COLORES["exito"], on_click=add_p)], alignment="spaceBetween"),
                    ft.Container(content=col_problemas, padding=10, border=ft.border.all(1, COLORES["borde"]), border_radius=5),
                ], scroll="auto", spacing=10)
                
                actions = [
                    ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg, 'open', False), page.overlay.remove(dlg) if dlg in page.overlay else None, page.update())),
                    ft.ElevatedButton("Guardar Cambios", bgcolor=COLORES["exito"], color=COLORES["fondo"], on_click=save_task)
                ]
            else:
                # --- MODO LECTURA (Tareas Globales) ---
                content = ft.Column([
                    ft.Text(f"Título: {data.get('title')}", weight="bold", size=18, color=COLORES["primario"]),
                    ft.Text(f"Descripción: {data.get('description')}"),
                    ft.Text(f"Tiempo estimado: {int(data.get('max_time', 3600)/60)} minutos", italic=True),
                    ft.Divider(),
                    ft.Text("Rúbricas de Evaluación:", weight="bold", color=COLORES["primario"]),
                    ft.Column([ft.Text(f"• {r.get('dimension')}: {r.get('descripcion')}", size=12) for r in data.get("rubricas",[])]),
                    ft.Divider(),
                    ft.Text("Problemas:", weight="bold", color=COLORES["primario"]),
                    ft.Column([ft.Text(f"{p['id']}. {p['enunciado']}", size=12) for p in data.get("problemas",[])]),
                ], scroll="auto", spacing=10)
                actions = [ft.TextButton("Cerrar", on_click=lambda e: (setattr(dlg, 'open', False), page.overlay.remove(dlg) if dlg in page.overlay else None, page.update()))]

            dlg = ft.AlertDialog(
                title=ft.Text("Editor de Tareas" if is_mine else "Detalles de la Tarea"),
                content=ft.Container(width=700, height=600, content=content),
                actions=actions
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
        
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
            try:
                r1 = auth_request("GET", "/api/teacher/my-exercises")
                if r1 and r1.status_code == 200:
                    state["my_exercises"] = r1.json()
                elif r1 and r1.status_code == 401:
                    flash("Sesión expirada. Por favor inicia sesión de nuevo.", ok=False)
                    return
                r2 = auth_request("GET", "/api/exercises/available")
                if r2 and r2.status_code == 200:
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
            res = auth_request("PUT", "/api/teacher/my-exercises/toggle", json={"filename": filename})
            if res and res.status_code == 200:
                data = res.json()
                is_active = data.get("is_active", False)
                status_str = "Activo (visible para estudiantes)" if is_active else "Inactivo (oculto para estudiantes)"
                flash(f"Ejercicio {status_str}", ok=is_active)
                load_exercises()
            else:
                flash("Error al cambiar estado", ok=False)
                page.update()
                
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
                            on_click=lambda e, f=ex_data.get("practica_id") or ex_data.get("filename"): toggle_exercise_status(e, f)
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
                        on_click=lambda e, item=ex_data: open_exercise_dialog(item)
                    )
                    
                # --- 1. Filtrar y Ordenar MIS TAREAS ---
                filtered_mine = [e for e in safe_my_exercises if state["filter_my_tasks"] in e.get("title", "").lower()]
                filtered_mine.sort(key=lambda x: x.get("title", "").lower(), reverse=(state["sort_my_tasks"] == "desc"))
                if state["filter_tasks_class"] != "Todas las clases":
                    clase_actual = next((c for c in state["classes"] if c["nombre"] == state["filter_tasks_class"]), None)
                    if clase_actual:
                        tareas_clase = {t["filename"] for t in clase_actual["tareas"]}
                        filtered_mine = [e for e in filtered_mine if e["filename"] in tareas_clase]
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
                try:
                    col_mine.update()
                    col_available.update()
                except Exception:
                    pass
                page.update()
                
        tab_exercises = ft.Container(
            content=ft.Column([
                # Columnas divididas
                ft.Row([
                    # COLUMNA IZQUIERDA: MIS TAREAS
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.ElevatedButton("Subir PDF con IA", icon=ft.Icons.AUTO_AWESOME, bgcolor=COLORES["accento"], color=COLORES["primario"], on_click=lambda _: file_picker.pick_files(allowed_extensions=["pdf"])),
                                ft.Text("Catálogo local de tareas seleccionadas", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_exercises)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([search_my_tasks, filter_tasks_class_dropdown, sort_btn_my_tasks], spacing=5),
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
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_exercises)
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
                
        def load_data_filtered(e=None):
            if e and hasattr(e, 'control'):
                e.control.disabled = True
                page.update()
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
            if e and hasattr(e, 'control'):
                e.control.disabled = False
                page.update()
                
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
                            ft.IconButton(ft.Icons.SEARCH, icon_size=20, on_click=load_data_filtered, icon_color=COLORES["primario"], tooltip="Aplicar Filtros")
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
            "Detener Sesión" if is_session_active else "Iniciar Sesión en Vivo", 
            icon=ft.Icons.STOP if is_session_active else ft.Icons.PLAY_ARROW,
            bgcolor=COLORES["error"] if is_session_active else COLORES["exito"],
            color=COLORES["texto"],
            height=40,
            on_click=lambda e: toggle_session(e)
        )

        if is_session_active:
            session_status_text.value = "🔴 EN VIVO: Recibiendo alertas..."
            session_status_text.color = COLORES["error"]
            try:
                if not sio.connected:
                    sio.connect(BASE)
            except: pass
        else:
            session_status_text.value = "Sesión Inactiva"
            session_status_text.color = COLORES["subtitulo"]

        # Botón para descargar reporte (Oculto por defecto)
        download_live_report_btn = ft.ElevatedButton(
            "Descargar Reporte Excel", 
            icon=ft.Icons.DOWNLOAD,
            bgcolor=COLORES["primario"],
            color=COLORES["fondo"],
            height=40,
            visible=False
        )

        # --- NUEVO CUADRO DE CONFIRMACIÓN PARA DETENER LA CLASE ---
        stop_session_dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORES["advertencia"]), ft.Text("Finalizar Sesión en Vivo")]),
            content=ft.Text("¿Estás seguro de que deseas detener el monitoreo en vivo?\n\nAl hacerlo, dejarás de recibir alertas en tiempo real y se generará el reporte cualitativo final de la clase."),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: close_stop_session_dlg()),
                ft.ElevatedButton("Detener y Generar Reporte", color=COLORES["fondo"], bgcolor=COLORES["error"], on_click=lambda e: confirm_stop_session(e))
            ]
        )
        if stop_session_dlg not in page.overlay:
            page.overlay.append(stop_session_dlg)

        def close_stop_session_dlg():
            stop_session_dlg.open = False
            page.update()

        def confirm_stop_session(e):
            e.control.disabled = True 
            page.update()
            close_stop_session_dlg()
            nonlocal is_session_active
            is_session_active = False
            save_k(page, "is_live_session_active", False)
            page.client_storage.remove("live_session_start_time")
            start_session_btn.text = "Iniciar Sesión en Vivo"
            start_session_btn.icon = ft.Icons.PLAY_ARROW
            start_session_btn.bgcolor = COLORES["exito"]
            session_status_text.value = "Sesión Inactiva"
            session_status_text.color = COLORES["subtitulo"]
            if sio.connected:
                sio.disconnect()
            
            if "live_session_start" in state:
                session_start_local = state["live_session_start"]
                session_end_local = dt.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None).isoformat()
                
                flash("Procesando análisis cualitativo con IA... Un momento...", ok=True, ms=4000)
                
                def generar_reporte():
                    res = auth_request("POST", "/api/teacher/live-session/generate", json={
                        "start_time": session_start_local, 
                        "end_time": session_end_local
                    }, timeout=60)
                    
                    if res and res.status_code == 200:
                        report_id = res.json().get("report_id")
                        download_live_report_btn.visible = True
                        download_live_report_btn.on_click = lambda e: page.launch_url(f"{BASE}/api/teacher/live-session/download?token={state['token']}&report_id={report_id}")
                        flash("¡Análisis de sesión generado! Listo para descargar", ok=True, ms=5000)
                    else:
                        try:
                            flash(res.json().get("error", "Error generando reporte"), ok=False)
                        except:
                            flash("No hubo datos suficientes para generar reporte", ok=False)
                    page.update()
                    
                threading.Thread(target=generar_reporte, daemon=True).start()
                del state["live_session_start"]
                
            e.control.disabled = False
            page.update()
            
        def toggle_session(e):
            nonlocal is_session_active
            if not is_session_active:
                is_session_active = True
                save_k(page, "is_live_session_active", True)
                state["live_session_start"] = dt.datetime.now(ZoneInfo("America/Tijuana")).replace(tzinfo=None).isoformat()
                save_k(page, "live_session_start_time", state["live_session_start"])
                download_live_report_btn.visible = False
                start_session_btn.text = "Detener Sesión"
                start_session_btn.icon = ft.Icons.STOP
                start_session_btn.bgcolor = COLORES["error"]
                session_status_text.value = "🔴 EN VIVO: Recibiendo alertas..."
                session_status_text.color = COLORES["error"]
                
                try:
                    if not sio.connected:
                        sio.connect(BASE) 
                except Exception as err:
                    flash(f"Error de conexión: {err}", ok=False)
                    is_session_active = False
                    start_session_btn.text = "Iniciar Sesión en Vivo"
                    start_session_btn.icon = ft.Icons.PLAY_ARROW
                    start_session_btn.bgcolor = COLORES["exito"]
                    session_status_text.value = "Sesión Inactiva"
                    session_status_text.color = COLORES["subtitulo"]
                page.update()
            else:
                stop_session_dlg.open = True
                page.update()

        def load_full_dashboard():
            reset_inactivity_timer()
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
                        session_status_text
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
        state["group_by_pending_A"] = "practica"
        state["group_by_pending_B"] = "problema"
        state["filter_completed_grades"] = ""
        state["group_by_completed_A"] = "practica"
        state["group_by_completed_B"] = "problema"
        
        search_completed_grades = ft.TextField(
            hint_text="Nombre o correo de estudiante...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=2,
            on_change=lambda e: update_grade_filters("completed", e.control.value)
        )

        search_pending_grades = ft.TextField(
            hint_text="Nombre o correo de estudiante...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=12,
            content_padding=10,
            border_radius=10,
            bgcolor=COLORES["fondo"],
            color=COLORES["texto"],
            expand=2,
            on_change=lambda e: update_grade_filters("pending", e.control.value)
        )
        
        def update_grade_grouping(target, is_A, value):
            if target == "completed":
                old_val_A = state["group_by_completed_A"]
                old_val_B = state["group_by_completed_B"]
                
                if is_A:
                    if value == old_val_B:
                        state["group_by_completed_B"] = old_val_A
                        group_completed_B_dropdown.value = old_val_A
                    state["group_by_completed_A"] = value
                else:
                    if value == old_val_A:
                        state["group_by_completed_A"] = old_val_B
                        group_completed_A_dropdown.value = old_val_B
                    state["group_by_completed_B"] = value
                
                group_completed_A_dropdown.update()
                group_completed_B_dropdown.update()
            else:
                old_val_A = state["group_by_pending_A"]
                old_val_B = state["group_by_pending_B"]
                
                if is_A:
                    if value == old_val_B:
                        state["group_by_pending_B"] = old_val_A
                        group_pending_B_dropdown.value = old_val_A
                    state["group_by_pending_A"] = value
                else:
                    if value == old_val_A:
                        state["group_by_pending_A"] = old_val_B
                        group_pending_A_dropdown.value = old_val_B
                    state["group_by_pending_B"] = value
                
                group_pending_A_dropdown.update()
                group_pending_B_dropdown.update()
            
            render_grades()

        def get_opciones():
            return [
                ft.dropdown.Option("fecha", "Fecha"),
                ft.dropdown.Option("practica", "Tarea"),
                ft.dropdown.Option("problema", "Ejercicio"),
                ft.dropdown.Option("estudiante", "Estudiante"),
            ]

        group_completed_A_dropdown = ft.Dropdown(
            label="Filtrar por", options=get_opciones(), value="practica",
            expand=1, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"], content_padding=10,
            on_change=lambda e: update_grade_grouping("completed", True, e.control.value)
        )
        group_completed_B_dropdown = ft.Dropdown(
            label="Seguido de", options=get_opciones(), value="problema",
            expand=1, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"], content_padding=10,
            on_change=lambda e: update_grade_grouping("completed", False, e.control.value)
        )

        group_pending_A_dropdown = ft.Dropdown(
            label="Filtrar por", options=get_opciones(), value="practica",
            expand=1, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"], content_padding=10,
            on_change=lambda e: update_grade_grouping("pending", True, e.control.value)
        )
        group_pending_B_dropdown = ft.Dropdown(
            label="Seguido de", options=get_opciones(), value="problema",
            expand=1, text_size=12, border_color=COLORES["primario"], color=COLORES["texto"], content_padding=10,
            on_change=lambda e: update_grade_grouping("pending", False, e.control.value)
        )

        col_completed_grades = ft.ListView(expand=True, spacing=10)
        col_pending_grades = ft.ListView(expand=True, spacing=10)
        
        grade_llm_score_field = ft.TextField(
            label="Calificación Sugerida", 
            read_only=True, 
            text_align=ft.TextAlign.CENTER, 
            bgcolor=COLORES["borde"],
            expand=1
        )
        grade_score_field = ft.TextField(
            label="Calificación Asignada",
            hint_text="Pendiente",
            text_align=ft.TextAlign.CENTER,
            input_filter=ft.InputFilter(allow=True, regex_string=r"^[0-9.]*$"),
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
        
        delete_eval_dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=COLORES["error"]), ft.Text("Confirmar Eliminación")]),
            content=ft.Text("Estás a punto de eliminar definitivamente esta evaluación de la base de datos.\n\nEsto es útil si el estudiante reenvió la misma respuesta varias veces y quieres limpiar duplicados. ¿Deseas proceder?"),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: close_delete_eval_dlg()),
                ft.ElevatedButton("Eliminar Permanentemente", color=COLORES["fondo"], bgcolor=COLORES["error"], on_click=lambda e: confirm_delete_eval(e))
            ]
        )
        
        def close_and_refresh_grades(e=None):
            load_grades()
            page.update()
        
        grade_dlg = ft.AlertDialog(
            title=ft.Container(content=grade_student_label, alignment=ft.alignment.center),
            actions_alignment=ft.MainAxisAlignment.CENTER,
            on_dismiss=close_and_refresh_grades
        )
            
        if grade_dlg not in page.overlay:
            page.overlay.append(grade_dlg)
            
        if delete_eval_dlg not in page.overlay:
            page.overlay.append(delete_eval_dlg)
            
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
            
        def confirm_delete_eval(e):
            e.control.disabled = True
            page.update()
            eval_id = state.get("delete_target_id")
            if eval_id:
                res = auth_request("DELETE", f"/api/teacher/grades/{eval_id}")
                if res and res.status_code == 200:
                    flash("Evaluación eliminada correctamente de la base de datos.", ok=True)
                    load_grades()
                else:
                    flash("Error al eliminar la evaluación.", ok=False)
            e.control.disabled = False
            close_delete_eval_dlg()

        def submit_grade(eval_id, action, score=None, comment=None):
            if getattr(page, "_is_submitting_grade", False):
                return False
            page._is_submitting_grade = True
            try:
                payload = {"id": eval_id, "action": action}
                if action == "edit":
                    payload["score"] = score
                    payload["comment"] = comment
                    
                res = auth_request("POST", "/api/teacher/grades/submit", json=payload)
                if res and res.status_code == 200:
                    load_grades()
                    return True
                else:
                    return False
            finally:
                page._is_submitting_grade = False
                if hasattr(page, "session_id") and page.session_id:
                    try:
                        page.update()
                    except AssertionError:
                        pass
                        
        def open_grade_dialog(initial_item, is_completed):
            with ui_lock:
                master_students = state.get("students", [])
                master_practices = [ex for ex in state.get("my_exercises", []) if isinstance(ex, dict)]
                try:
                    sel_student_idx = next(i for i, s in enumerate(master_students) if s["email"] == initial_item["correo"])
                except StopIteration: sel_student_idx = 0
                try:
                    sel_practice_idx = next(i for i, p in enumerate(master_practices) if p["title"] == initial_item["practica"] or p["filename"] == initial_item["practica"])
                except StopIteration: sel_practice_idx = 0
                all_evals = state.get("pending_grades", []) + state.get("completed_grades", [])
                sel_problem_id = int(initial_item["problema_id"])
                status_msg_dlg = ft.Text("", weight="bold", size=14, text_align=ft.TextAlign.CENTER)
                if "revised_evals" not in state:
                    state["revised_evals"] = set()
                if "teacher_clipboard" not in state:
                    state["teacher_clipboard"] = load_k(page, "teacher_clipboard_data", [
                        "Falta desarrollar el procedimiento.",
                        "Excelente análisis del problema.",
                        "Revisa tus operaciones matemáticas."
                    ])
                    
                def show_dialog_feedback(text, color):
                    status_msg_dlg.value = text
                    status_msg_dlg.color = color
                    page.update()
                    
                    def clear_msg():
                        time.sleep(3)
                        status_msg_dlg.value = ""
                        try:
                            if page.is_alive: page.update()
                        except: pass
                    
                    threading.Thread(target=clear_msg, daemon=True).start()
                    
                def add_to_clipboard(e):
                    val = clipboard_input.value.strip()
                    if val:
                        state["teacher_clipboard"].append(val)
                        save_k(page, "teacher_clipboard_data", state["teacher_clipboard"])
                        clipboard_input.value = ""
                        render_clipboard()

                def remove_from_clipboard(idx):
                    state["teacher_clipboard"].pop(idx)
                    save_k(page, "teacher_clipboard_data", state["teacher_clipboard"])
                    render_clipboard()

                def append_to_student_comment(text):
                    current = grade_comment_field.value or ""
                    grade_comment_field.value = f"{current}\n{text}".strip()
                    page.update() 

                clipboard_list = ft.ListView(expand=True, spacing=10)
                clipboard_input = ft.TextField(hint_text="Nuevo comentario...", text_size=14, expand=True, on_submit=add_to_clipboard)

                def render_clipboard():
                    items = []
                    for i, text in enumerate(state["teacher_clipboard"]):
                        items.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Text(text, size=14, color=COLORES["texto"], expand=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.IconButton(ft.Icons.ADD_COMMENT, icon_color=COLORES["exito"], icon_size=16, tooltip="Insertar", on_click=lambda e, t=text: append_to_student_comment(t)),
                                    ft.IconButton(ft.Icons.DELETE, icon_color=COLORES["error"], icon_size=16, tooltip="Borrar", on_click=lambda e, idx=i: remove_from_clipboard(idx)),
                                ]),
                                bgcolor=COLORES["fondo"], padding=5, border_radius=5, border=ft.border.all(1, COLORES["borde"])
                            )
                        )
                    clipboard_list.controls = items
                    try: clipboard_list.update()
                    except: pass
                    
                ancho_dialogo = page.width * 0.8
                alto_dialogo = page.height * 0.8
                
                left_panel = ft.Container(
                    col={"xs": 12, "lg": 3},
                    height=alto_dialogo,
                    content=ft.Column([
                        ft.Text("📋 Portapapeles Docente", weight="bold", color=COLORES["primario"]),
                        ft.Row([clipboard_input, ft.IconButton(ft.Icons.ADD, on_click=add_to_clipboard, icon_color=COLORES["primario"])]),
                        ft.Divider(),
                        clipboard_list
                    ]),
                    bgcolor=COLORES["accento"], padding=15, border_radius=10, border=ft.border.all(1, COLORES["borde"])
                )
                
                llm_rubric_list = ft.ListView(expand=True, spacing=10)
                
                right_panel = ft.Container(
                    col={"xs": 12, "lg": 3},
                    height=alto_dialogo,
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.AUTO_AWESOME, color=COLORES["advertencia"]),
                            ft.Text("Justificación IA", weight="bold", color=COLORES["primario"])
                        ]),
                        ft.Divider(),
                        llm_rubric_list
                    ]),
                    bgcolor=COLORES["accento"], padding=15, border_radius=10, border=ft.border.all(1, COLORES["borde"])
                )

                btn_approve = ft.ElevatedButton("Aprobar Sugerencia", bgcolor=COLORES["boton"], color=COLORES["fondo"])
                btn_modify = ft.ElevatedButton("Modificar Calificación", bgcolor=COLORES["exito"], color=COLORES["fondo"])

                lbl_nav_student = ft.Text("", weight="bold", size=20, color=COLORES["texto"])
                lbl_nav_practice = ft.Text("", size=16, color=COLORES["primario"])
                lbl_nav_problem = ft.Text("", size=14, weight="bold", color=COLORES["texto"])
                lbl_nav_date = ft.Text("", size=12, color=COLORES["subtitulo"])
                
                status_badge = ft.Container(
                    content=ft.Text("PENDIENTE", weight="bold", size=12, color=COLORES["fondo"]),
                    bgcolor=COLORES["error"],
                    padding=ft.padding.symmetric(horizontal=10, vertical=5),
                    border_radius=5
                )

                def nav_change(level, delta):
                    nonlocal sel_student_idx, sel_practice_idx, sel_problem_id
                    if level == "student":
                        sel_student_idx = (sel_student_idx + delta) % len(master_students)
                        sync_hierarchical_view()
                    elif level == "practice":
                        sel_practice_idx = (sel_practice_idx + delta) % len(master_practices)
                        # Al cambiar de práctica, empezamos buscando el primer problema entregado de la nueva
                        sel_problem_id = get_next_available_problem(0, 1) 
                        sync_hierarchical_view()
                    elif level == "problem":
                        # Saltamos al siguiente/anterior problema que REALMENTE tenga respuesta
                        sel_problem_id = get_next_available_problem(sel_problem_id, delta)
                        sync_hierarchical_view()

                def get_next_available_problem(current_id, delta):
                    # 1. Obtener todas las respuestas de este alumno en esta práctica
                    student = master_students[sel_student_idx]
                    practice = master_practices[sel_practice_idx]
                    
                    # Buscamos en la lista de evaluaciones precargadas
                    all_evals = state.get("pending_grades", []) + state.get("completed_grades", [])
                    # Filtramos solo las que pertenecen a este alumno y esta práctica
                    entregas = [
                        int(ev["problema_id"]) for ev in all_evals 
                        if ev["correo"] == student["email"] 
                        and (ev["practica"] == practice["title"] or ev["practica"] == practice["filename"])
                    ]
                    entregas = sorted(list(set(entregas))) # Ordenados y sin duplicados
                    
                    if not entregas: return current_id
                    
                    if delta > 0: # Buscando siguiente
                        siguientes = [p for p in entregas if p > current_id]
                        return siguientes[0] if siguientes else current_id
                    else: # Buscando anterior
                        anteriores = [p for p in entregas if p < current_id]
                        return anteriores[-1] if anteriores else current_id

                def create_nav_row(label_ctrl, level):
                    return ft.Row([
                        ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: nav_change(level, -1), icon_color=COLORES["primario"]),
                        ft.Container(content=label_ctrl, alignment=ft.alignment.center, expand=True),
                        ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: nav_change(level, 1), icon_color=COLORES["primario"]),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=0)

                grade_dlg.title = ft.Column([
                    create_nav_row(lbl_nav_student, "student"),
                    create_nav_row(lbl_nav_practice, "practice"),
                    create_nav_row(lbl_nav_problem, "problem"),
                    ft.Container(
                        content=ft.Row([lbl_nav_date, status_badge], alignment=ft.MainAxisAlignment.CENTER, spacing=15), 
                        padding=ft.padding.only(top=5)
                    )
                ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

                center_grading_content = ft.Container(
                    expand=True, 
                    content=ft.Column([
                        grade_response_container,
                        ft.Row([
                            grade_llm_score_field,
                            grade_score_field
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=20),
                        grade_comment_field,
                    ], tight=False, spacing=15, scroll=ft.ScrollMode.AUTO),
                    padding=10
                )

                center_panel = ft.Container(
                    col={"xs": 12, "lg": 6},
                    height=alto_dialogo,
                    content=center_grading_content
                )

                grade_dlg.content = ft.Container(
                    width=ancho_dialogo,
                    height=alto_dialogo,
                    content=ft.Column([
                        ft.ResponsiveRow([
                            left_panel,
                            center_panel,
                            right_panel
                        ], vertical_alignment=ft.CrossAxisAlignment.START)
                    ], scroll=ft.ScrollMode.AUTO)
                )

                def sync_hierarchical_view():
                    student = master_students[sel_student_idx]
                    practice = master_practices[sel_practice_idx]
                    
                    lbl_nav_student.value = f"{student.get('nombre', 'Estudiante')}"
                    lbl_nav_practice.value = f"📚 {practice['title']}"
                    lbl_nav_problem.value = f"Ejercicio #{sel_problem_id}"
                    
                    all_evals = state.get("pending_grades", []) + state.get("completed_grades", [])
                    item = next((ev for ev in all_evals if ev["correo"] == student["email"] 
                                 and (ev["practica"] == practice["title"] or ev["practica"] == practice["filename"])
                                 and int(ev["problema_id"]) == sel_problem_id), None)
                    
                    state["current_eval_item"] = item
                    
                    if not item:
                        lbl_nav_date.value = "Sin entrega registrada"
                        grade_response_container.content = ft.Container(
                            content=ft.Text("El estudiante aún no ha enviado respuesta para este ejercicio.", italic=True, color=COLORES["subtitulo"]),
                            padding=20, alignment=ft.alignment.center
                        )
                        btn_approve.visible = btn_modify.visible = False
                        grade_llm_score_field.value = "-/10"
                        grade_score_field.value = ""
                        grade_comment_field.value = ""
                        llm_rubric_list.controls.clear()
                    else:
                        btn_approve.visible = btn_modify.visible = True
                        date_str = item.get("fecha", "")[:10] if item.get("fecha") else "Fecha desconocida"
                        lbl_nav_date.value = f"🕒 Entregado el: {date_str}"
                        
                        enunciado = "Enunciado no disponible."
                        for p in practice.get("problemas", []):
                            if str(p.get("id")).split('.')[0] == str(sel_problem_id):
                                enunciado = p.get("enunciado", "Enunciado no disponible.")
                                break

                        grade_response_container.content = ft.Column([
                            ft.Text(f"Enunciado:", weight="bold", size=14, color=COLORES["primario"]),
                            ft.Text(enunciado, size=14, color=COLORES["texto"]),
                            ft.Divider(height=1, color=COLORES["borde"]),
                            ft.Text("Respuesta del Estudiante:", weight="bold", size=14, color=COLORES["primario"]),
                            ft.TextField(value=item['respuesta'], read_only=True, multiline=True, min_lines=3, max_lines=8, border=ft.InputBorder.NONE, text_align=ft.TextAlign.JUSTIFY)
                        ], spacing=5)

                        raw_llm = item.get('llm_score', 0)
                        grade_llm_score_field.value = f"{raw_llm}/10"
                        
                        t_score = item.get('teacher_score')
                        grade_score_field.value = str(t_score) if t_score is not None else ""
                        
                        is_revised = item["id"] in state["revised_evals"] or item.get("status") in ["approved", "edited"]
                        if is_revised:
                            grade_score_field.bgcolor = COLORES["fondo"]
                            grade_score_field.color = COLORES["exito"]
                            grade_score_field.text_style = ft.TextStyle(weight="bold", size=18)
                        else:
                            grade_score_field.bgcolor = COLORES["fondo"]
                            grade_score_field.color = COLORES["texto"]
                            grade_score_field.text_style = ft.TextStyle(weight="normal", size=18)
                            
                        raw_comment = item.get('llm_comment', '')
                        comentario_general = raw_comment 
                        llm_rubric_list.controls.clear()
                        try:
                            import json
                            rubric_data = json.loads(raw_comment)
                            comentario_general = rubric_data.get("comentario", raw_comment)
                            if "rubricas" in rubric_data:
                                for rub in rubric_data["rubricas"]:
                                    llm_rubric_list.controls.append(
                                        ft.Container(
                                            content=ft.Column([
                                                ft.Text(rub.get("dimension", "Dimensión"), weight="bold", size=14, color=COLORES["secundario"]),
                                                ft.Text(rub.get("observacion", ""), size=14, color=COLORES["texto"], text_align=ft.TextAlign.JUSTIFY)
                                            ], spacing=2),
                                            bgcolor=COLORES["fondo"], padding=8, border_radius=5, border=ft.border.all(1, COLORES["borde"])
                                        )
                                    )
                        except:
                            llm_rubric_list.controls.append(ft.Text("Evaluación general, sin desglose de rúbricas.", size=12, color=COLORES["texto"], italic=True))

                        t_comment = item.get('teacher_comment')
                        if t_comment and not str(t_comment).strip().startswith("{") and not str(t_comment).strip().startswith("["):
                            grade_comment_field.value = t_comment if is_revised else comentario_general
                        else:
                            grade_comment_field.value = comentario_general
                            
                        if is_revised:
                            status_badge.content.value = "REVISADO"
                            status_badge.bgcolor = COLORES["exito"]
                        else:
                            status_badge.content.value = "PENDIENTE"
                            status_badge.bgcolor = COLORES["error"]

                    render_clipboard()
                    page.update()

                def handle_approve(e):
                    e.control.disabled = True
                    page.update()
                    item = state["current_eval_item"]
                    raw_score = grade_score_field.value
                    score = float(raw_score) if raw_score else 0.0
                    comentario_actual = grade_comment_field.value
                    exito = submit_grade(item['id'], "approve", score, comentario_actual)
                    if exito:
                        state["revised_evals"].add(item["id"])
                        item['teacher_score'] = score
                        item['teacher_comment'] = comentario_actual
                        item['status'] = "approved"
                        status_badge.content.value = "REVISADO"
                        status_badge.bgcolor = COLORES["exito"]
                        show_dialog_feedback("✅ Calificación aprobada correctamente", COLORES["exito"])
                    else:
                        show_dialog_feedback("❌ Error al guardar en el servidor", COLORES["error"])
                    e.control.disabled = False
                    page.update()
                    
                def handle_modify(e):
                    item = state["current_eval_item"]
                    val = grade_score_field.value
                    if not val:
                        show_dialog_feedback("⚠️ Ingresa una calificación antes de modificar", COLORES["error"])
                        return
                    try:
                        score = float(val)
                    except ValueError:
                        show_dialog_feedback("⚠️ Ingresa un número válido", COLORES["error"])
                        return
                    e.control.disabled = True
                    page.update()
                    
                    exito = submit_grade(item['id'], "edit", score, grade_comment_field.value)
                    if exito:
                        state["revised_evals"].add(item["id"])
                        item['teacher_score'] = score
                        item['teacher_comment'] = grade_comment_field.value
                        sync_hierarchical_view()
                        show_dialog_feedback("📝 Calificación actualizada", COLORES["exito"])
                    else:
                        show_dialog_feedback("❌ Error al guardar en el servidor", COLORES["error"])
                    e.control.disabled = False
                    page.update()

                btn_approve.on_click = handle_approve
                btn_modify.on_click = handle_modify

                grade_dlg.actions = [
                    ft.Column([
                        ft.Container(content=status_msg_dlg, alignment=ft.alignment.center),
                        ft.Row([btn_approve, btn_modify], alignment=ft.MainAxisAlignment.CENTER, spacing=20)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
                ]

                sync_hierarchical_view()
                grade_dlg.open = True
                page.update()
                
        def update_grade_filters(target, value):
            if target == "completed": state["filter_completed_grades"] = value.lower()
            else: state["filter_pending_grades"] = value.lower()
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
                                ft.Text(
                                    f"{item.get('nombre', 'Estudiante')}",
                                    weight="bold",
                                    size=14,
                                    color=COLORES["texto"]
                                ),
                                ft.Text(
                                    f"{item['correo']}",
                                    size=12,
                                    color=COLORES["subtitulo"]
                                ),
                                ft.Row([
                                    ft.Icon(
                                        ft.Icons.MENU_BOOK,
                                        size=12,
                                        color=COLORES["primario"]
                                    ),
                                    ft.Text(
                                        f"{item.get('titulo_practica', item['practica'])} - P{item['problema_id']}",
                                        size=12,
                                        color=COLORES["primario"]
                                    ),
                                    ft.Container(width=5),
                                    ft.Icon(
                                        ft.Icons.EVENT_NOTE,
                                        size=12,
                                        color=COLORES["subtitulo"]
                                    ),
                                    ft.Text(
                                        f"{date_str}",
                                        size=12,
                                        color=COLORES["subtitulo"]
                                    )
                                ], spacing=5)
                            ], expand=True),
                            ft.Column([
                                ft.Text(
                                    f"{score_display}/10",
                                    color=score_color,
                                    weight="bold",
                                    size=16
                                ),
                                ft.Text(
                                    "Evaluación IA",
                                    size=10,
                                    italic=True
                                ) if not is_completed else ft.Text("Nota Final", size=10, italic=True)
                            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.END),
                            ft.Column([
                                ft.IconButton(
                                    ft.Icons.DELETE_FOREVER,
                                    on_click=lambda e,
                                    i=item: open_delete_eval_dlg(i['id']),
                                    icon_color=COLORES["error"],
                                    tooltip="Eliminar Duplicado")
                            ], spacing=0, alignment=ft.MainAxisAlignment.CENTER)
                        ]),
                        bgcolor=COLORES["fondo"],
                        padding=10,
                        border_radius=5,
                        border=ft.border.all(1, COLORES["borde"]),
                        margin=ft.margin.only(bottom=5),
                        ink=True,
                        on_click=lambda e, i=item: open_grade_dialog(i, is_completed), 
                        tooltip="Hacer clic en cualquier lugar para abrir detalles y revisión de evaluación"
                    )

                def get_group_key(item, group_type):
                    if group_type == "fecha": return item.get("fecha", "")[:10]
                    elif group_type == "practica":
                        return item.get("titulo_practica") or item.get("practica", "Sin práctica")
                    elif group_type == "problema": return f"Ejercicio #{item.get('problema_id', '?')}"
                    elif group_type == "estudiante": return item.get("nombre", item.get("correo"))
                    return "General"

                def build_grouped_list(items, group_A, group_B, is_completed):
                    items.sort(key=lambda x: (get_group_key(x, group_A), get_group_key(x, group_B), x.get("fecha", "")), reverse=True)
                    grupos = {}
                    for item in items:
                        g_key = f"{get_group_key(item, group_A)} ➔ {get_group_key(item, group_B)}"
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

                filtered_comp = [g for g in state["completed_grades"] if state["filter_completed_grades"] in g.get("correo", "").lower() or state["filter_completed_grades"] in g.get("nombre", "").lower()]
                filtered_pend = [g for g in state["pending_grades"] if state["filter_pending_grades"] in g.get("correo", "").lower() or state["filter_pending_grades"] in g.get("nombre", "").lower()]
                filtered_comp.sort(key=lambda x: (get_group_key(x, state["group_by_completed_A"]), get_group_key(x, state["group_by_completed_B"]), x.get("fecha", "")), reverse=True)
                filtered_pend.sort(key=lambda x: (get_group_key(x, state["group_by_pending_A"]), get_group_key(x, state["group_by_pending_B"]), x.get("fecha", "")), reverse=True)
                state["nav_comp"] = filtered_comp
                state["nav_pend"] = filtered_pend
                if not filtered_comp: nuevas_completadas.append(ft.Text("No hay evaluaciones completadas", color=COLORES["subtitulo"]))
                else: nuevas_completadas.extend(build_grouped_list(filtered_comp, state["group_by_completed_A"], state["group_by_completed_B"], True))
                if not filtered_pend: nuevas_pendientes.append(ft.Text("No hay evaluaciones pendientes", color=COLORES["subtitulo"]))
                else: nuevas_pendientes.extend(build_grouped_list(filtered_pend, state["group_by_pending_A"], state["group_by_pending_B"], False))
                col_completed_grades.controls = nuevas_completadas
                col_pending_grades.controls = nuevas_pendientes
                
                try:
                    col_completed_grades.update()
                    col_pending_grades.update()
                except Exception:
                    pass
                
        def download_grades_excel(e):
            url = f"{BASE}/api/teacher/grades/download?token={state['token']}"
            page.launch_url(url)

        btn_download_excel = ft.IconButton(
            icon=ft.Icons.TABLE_VIEW,
            icon_color=COLORES["primario"],
            icon_size=20,
            tooltip="Descargar Reporte Excel",
            on_click=download_grades_excel
        )
        
        tab_grading = ft.Container(
            content=ft.Column([
                ft.Row([
                    # COLUMNA IZQUIERDA: Completadas
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                btn_download_excel,
                                ft.Text("Evaluaciones Completadas", size=20, color=COLORES["primario"], expand=True, text_align=ft.TextAlign.CENTER),
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_grades)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([
                                search_completed_grades, 
                                group_completed_A_dropdown,
                                group_completed_B_dropdown
                            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
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
                                ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], icon_size=20, tooltip="Refrescar", on_click=refresh_grades)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([
                                search_pending_grades, 
                                group_pending_A_dropdown,
                                group_pending_B_dropdown
                            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
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
            state["expected_profile_email"] = email
            profile_content.controls = [
                ft.Container(content=ft.ProgressRing(color=COLORES["primario"]), alignment=ft.alignment.center, height=100)
            ]
            page.update()
            
            def fetch():
                res = auth_request("GET", f"/api/teacher/student-profile/{email}")
                if state.get("expected_profile_email") != email:
                    return
                if res and res.status_code == 200:
                    render_student_profile(res.json(), email)
                else:
                    profile_content.controls = [ft.Text("Error al cargar perfil", color=COLORES["error"])]
                    page.update()
            threading.Thread(target=fetch, daemon=True).start()
            
        def generate_report_for_practice(e, email, prac_name):
            e.control.disabled = True
            page.update()
            flash(f"Analizando interacciones con IA para {prac_name}... esto tomará unos segundos...", ok=True, ms=6000)
            def fetch():
                res = auth_request("POST", "/api/teacher/generate-report", json={"student_email": email, "practice_name": prac_name}, timeout=60)
                if res and res.status_code == 200:
                    flash("¡Reporte cualitativo generado con éxito!", ok=True)
                    load_student_profile(email)
                else:
                    flash("¡Error al generar el reporte con la IA!", ok=False)
                    e.control.disabled = False
                    page.update()
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
                                        ft.IconButton(ft.Icons.REFRESH, tooltip="Regenerar Reporte", icon_color=COLORES["subtitulo"], on_click=lambda e, pr=prac_name: generate_report_for_practice(e, email, pr))
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
                                    ft.ElevatedButton("Generar Reporte con IA", icon=ft.Icons.AUTO_AWESOME, bgcolor=COLORES["boton"], color=COLORES["texto"], on_click=lambda e, pr=prac_name: generate_report_for_practice(e, email, pr))
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
        
        # =========================================
        # PESTAÑA: Gestión de Clases
        # =========================================
        col_classes = ft.ListView(expand=True, spacing=10)
        def delete_class(e, class_id):
            e.control.disabled = True
            page.update()
            res = auth_request("DELETE", f"/api/teacher/classes/{class_id}")
            if res and res.status_code == 200:
                flash("Clase eliminada exitosamente", ok=True)
                load_classes()
            else:
                flash("Error al eliminar la clase", ok=False)
                e.control.disabled = False
                page.update()

        def open_create_class_dlg():
            nombre_input = ft.TextField(label="Nombre de la Clase (Ej: Grupo A)", expand=True)
            
            # Generamos checkboxes dinámicos basados en lo que el profe tiene en su estado
            estudiantes_checks = [ft.Checkbox(label=f"{s.get('nombre','')} ({s['email']})", value=False, data=s["email"]) for s in state.get("students", [])]
            tareas_checks = [ft.Checkbox(label=t["title"], value=False, data=t["filename"]) for t in state.get("my_exercises", []) if isinstance(t, dict)]
            
            def save_class(e):
                if not nombre_input.value.strip():
                    flash("El nombre de la clase es obligatorio", ok=False)
                    return
                
                # Extraer lo que el profe palomeó
                seleccionados_est = [c.data for c in estudiantes_checks if c.value]
                seleccionados_tar = [c.data for c in tareas_checks if c.value]
                
                e.control.disabled = True
                page.update()
                
                res = auth_request("POST", "/api/teacher/classes", json={
                    "nombre": nombre_input.value.strip(),
                    "estudiantes": seleccionados_est,
                    "tareas": seleccionados_tar
                })
                
                if res and res.status_code == 201:
                    flash("Clase creada con éxito", ok=True)
                    dlg.open = False
                    load_classes()
                else:
                    flash("Error al crear la clase", ok=False)
                    e.control.disabled = False
                    page.update()
                
            dlg = ft.AlertDialog(
                title=ft.Text("Crear Nueva Clase"),
                content=ft.Container(
                    width=500, height=450,
                    content=ft.Column([
                        nombre_input,
                        ft.Text("Selecciona Estudiantes:", weight="bold", color=COLORES["primario"]),
                        ft.Container(content=ft.ListView(estudiantes_checks, height=120), border=ft.border.all(1, COLORES["borde"]), padding=5, border_radius=5),
                        ft.Text("Selecciona Tareas:", weight="bold", color=COLORES["primario"]),
                        ft.Container(content=ft.ListView(tareas_checks, height=120), border=ft.border.all(1, COLORES["borde"]), padding=5, border_radius=5)
                    ], scroll=ft.ScrollMode.AUTO, spacing=10)
                ),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: (setattr(dlg, 'open', False), page.overlay.remove(dlg) if dlg in page.overlay else None, page.update())),
                    ft.ElevatedButton("Guardar Clase", on_click=save_class, bgcolor=COLORES["exito"], color=COLORES["fondo"])
                ]
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.update()

        def open_manage_class_dlg(clase):
            # Como aún no creamos un endpoint PUT para modificar clases existentes en el backend,
            # sugerimos temporalmente eliminar y recrear la clase.
            flash("Para modificar los alumnos o tareas, por favor elimina la clase y vuélvela a crear. (Edición nativa en desarrollo)", ok=False, ms=5000)
        def load_classes():
            res = auth_request("GET", "/api/teacher/classes")
            if res and res.status_code == 200:
                state["classes"] = res.json()
                render_classes()
                update_class_dropdowns()

        def render_classes():
            nuevas_clases = []
            for c in state["classes"]:
                # 1. Creamos el tile sin bordes
                tile = ft.ExpansionTile(
                    title=ft.Text(c["nombre"], weight="bold", color=COLORES["primario"]),
                    subtitle=ft.Text(f"{len(c['estudiantes'])} Estudiantes | {len(c['tareas'])} Tareas", size=12),
                    controls=[
                        ft.Container(
                            content=ft.Row([
                                ft.Column([
                                    ft.Text("Estudiantes en esta clase:", weight="bold", size=12),
                                    ft.ListView([ft.Text(f"• {e['nombre']}", size=11) for e in c["estudiantes"]], height=100)
                                ], expand=1),
                                ft.VerticalDivider(),
                                ft.Column([
                                    ft.Text("Tareas asignadas:", weight="bold", size=12),
                                    ft.ListView([ft.Text(f"• {t['title']}", size=11) for t in c["tareas"]], height=100)
                                ], expand=1),
                            ], height=150),
                            padding=15, bgcolor=COLORES["accento"]
                        ),
                        ft.Row([
                            ft.TextButton("Gestionar Miembros", icon=ft.Icons.EDIT, on_click=lambda e, cl=c: open_manage_class_dlg(cl)),
                            ft.IconButton(ft.Icons.DELETE, icon_color=COLORES["error"], on_click=lambda e, id=c["id"]: delete_class(e, id))
                        ], alignment=ft.MainAxisAlignment.END)
                    ]
                )
                
                # 2. Lo envolvemos en un contenedor para darle el estilo
                nuevas_clases.append(
                    ft.Container(
                        content=tile,
                        border=ft.border.all(1, COLORES["borde"]),
                        border_radius=10,
                        margin=ft.margin.only(bottom=10) # Separación visual entre clases
                    )
                )
                
            col_classes.controls = nuevas_clases if nuevas_clases else [ft.Text("No has creado clases aún.", italic=True)]
            page.update()

        def update_class_dropdowns():
            opts_estudiantes = [ft.dropdown.Option("Todas las clases")] + [ft.dropdown.Option(c["nombre"]) for c in state["classes"]]
            opts_tareas = [ft.dropdown.Option("Todas las clases")] + [ft.dropdown.Option(c["nombre"]) for c in state["classes"]]
            
            filter_students_class_dropdown.options = opts_estudiantes
            filter_tasks_class_dropdown.options = opts_tareas
            
            try:
                page.update()
            except Exception:
                pass

        tab_classes = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Mis Clases / Grupos", size=24, weight="bold", color=COLORES["primario"]),
                    ft.ElevatedButton("Nueva Clase", icon=ft.Icons.ADD, bgcolor=COLORES["boton"], color=COLORES["texto"], on_click=lambda _: open_create_class_dlg())
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(),
                col_classes
            ], expand=True),
            padding=20
        )
        
        # Tabs Principales
        tabs = ft.Tabs(
            selected_index=load_k(page, "current_tab_index", 0),
            animation_duration=300,
            on_change=lambda e: (
                save_k(page, "current_tab_index", e.control.selected_index),
                reset_inactivity_timer(),
                load_exercises() if e.control.selected_index == 1 else None,
                load_classes() if e.control.selected_index == 2 else None,
                load_grades() if e.control.selected_index == 3 else None,
                load_full_dashboard() if e.control.selected_index == 6 else None
            ),
            tabs=[
                ft.Tab(text="Estudiantes", icon=ft.Icons.GROUPS, content=tab_students),
                ft.Tab(text="Tareas", icon=ft.Icons.ASSIGNMENT, content=tab_exercises),
                ft.Tab(text="Clases", icon=ft.Icons.CLASS_, content=tab_classes),
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
        
        page.splash = ft.ProgressBar(color=COLORES["primario"])
        page.update()

        def _initial_load():
            threads = [
                threading.Thread(target=load_students,  daemon=True),
                threading.Thread(target=load_exercises, daemon=True),
                threading.Thread(target=load_grades,    daemon=True),
                threading.Thread(target=load_classes,   daemon=True),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            page.splash = None
            try:
                page.update()
            except Exception:
                pass
        threading.Thread(target=_initial_load, daemon=True).start()
        
    stored_token = load_k(page, "teacher_token")
    last_act_stored = load_k(page, "last_activity")
    
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
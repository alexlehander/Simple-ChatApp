import flet as ft
import requests, time, threading, os, json

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

BASE                    = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_CHAT        = f"{BASE}/chat"
BACKEND_URL_VERIFICAR   = f"{BASE}/verificar_respuesta"

# ---- Persistence helpers ----
STATE_KEYS = {
    "screen": "ui_screen",
    "code": "correo_identificacion",
    "current_problem": "current_problem_id",
    "answers": "answers_map",
    "chat": "chat_map",
    "timer_start": "timer_start_epoch",
    "pending_queue": "pending_queue_list",
}

def main(page: ft.Page):
    
    def on_disconnect(e):
        page.is_alive = False
        print("Cliente desconectado. Deteniendo hilos.")
    
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
    
    state = {
        "token": page.client_storage.get("teacher_token"),
        "last_activity": time.time(),
        "students": [],
        "dashboard_data": {},
        "my_exercises": [],
        "all_exercises": []
    }
    
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
                text_align=ft.TextAlign.CENTER
            ),
            alignment=ft.alignment.center
        )
        save_snack.bgcolor = COLORES["exito"] if ok else COLORES["error"]
        save_snack.duration = ms
        save_snack.open = True
        page.update()
        
    def check_session():
        # Leemos de MEMORIA (state) en lugar de consultar al navegador
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
            label="Filtrar Estudiante",
            expand=True,
            options=[ft.dropdown.Option("Todos los Estudiantes")], 
            value="Todos los Estudiantes",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            width=400
        )
        exercise_filter = ft.Dropdown(
            label="Filtrar Tarea",
            expand=True, 
            options=[ft.dropdown.Option("Todas las Tareas")], 
            value="Todas las Tareas",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            width=400,
            on_change=lambda e: update_problem_options()
        )
        
        problem_filter = ft.Dropdown(
            label="Ejercicio",
            width=100,
            options=[ft.dropdown.Option("Todos")],
            value="Todos",
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            text_size=12,
            content_padding=10,
            width=400,
            disabled=True
        )
        
        def update_problem_options():
            selected_task = exercise_filter.value
            if not selected_task or selected_task == "Todas las Tareas":
                problem_filter.options = [ft.dropdown.Option("Todos")]
                problem_filter.value = "Todos"
                problem_filter.disabled = True
            else:
                target = next((x for x in state["my_exercises"] if isinstance(x, dict) and x["filename"] == selected_task), None)
                if target:
                    num = target.get("num_problems", 1)
                    problem_filter.options = [ft.dropdown.Option("Todos")] + [ft.dropdown.Option(str(i)) for i in range(1, num + 1)]
                    problem_filter.disabled = False
                    problem_filter.value = "Todos"
                else:
                    problem_filter.disabled = True
            
            problem_filter.update()
            load_data_filtered()
            
        def update_dropdowns():
            student_filter.options = [ft.dropdown.Option("Todos los Estudiantes")] + [ft.dropdown.Option(e) for e in state["students"]]
            exercise_filter.options = [ft.dropdown.Option("Todas las Tareas")] + [
                ft.dropdown.Option(key=e["filename"], text=e["title"]) for e in state["my_exercises"] if isinstance(e, dict)
            ]
            problem_filter.value = "Todos"
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

            if not student_email or student_email == "Todos los Estudiantes":
                flash("Debes seleccionar un estudiante específico para enviar un mensaje.", ok=False)
                return
            if not task_filename or task_filename == "Todas las Tareas":
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
            if student_filter.value != "Todos los Estudiantes":
                params["student_email"] = student_filter.value
            if exercise_filter.value != "Todas las Tareas":
                params["practice_name"] = exercise_filter.value
                if problem_filter.value != "Todos" and problem_filter.value is not None:
                    pass
                    
            res = auth_request("GET", "/api/teacher/dashboard-data", params=params)
            if res and res.status_code == 200:
                render_data(res.json())
                
        def render_data(data):
            answers_col.controls.clear()
            chats_col.controls.clear()
            raw_answers = data.get("respuestas", [])
            raw_chats = data.get("chats", [])
            
            # --- FILTRO CLIENT-SIDE DE PROBLEMA ---
            target_prob = problem_filter.value
            if target_prob != "Todos" and target_prob is not None:
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
                        width=None, # Auto ancho
                        constraints=ft.BoxConstraints(max_width=400) # Evitar burbujas gigantes
                    )
                ], horizontal_alignment=align))
            
            # Si no hay datos tras filtrar
            if not answers_col.controls:
                answers_col.controls.append(ft.Text("No hay respuestas registradas con estos filtros", italic=True, color=COLORES["subtitulo"]))
            if not chats_col.controls:
                chats_col.controls.append(ft.Text("No hay historial de chat con estos filtros", italic=True, color=COLORES["subtitulo"]))
                
            page.update()
            
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
                
                ft.Divider(color="transparent", height=10),
                
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
        # PESTAÑA 4: Dashboard (Borrador)
        # =========================================
        dashboard_col = ft.Column(expand=True)
        
        def load_full_dashboard():
            # 1. Carga datos globales (sin filtros) para ver todo el panorama
            reset_inactivity_timer()
            res = auth_request("GET", "/api/teacher/dashboard-data") # Sin params trae todo
            if res and res.status_code == 200:
                state["dashboard_data"] = res.json()
                render_dashboard_view()
        
        def render_dashboard_view():
            status_res = auth_request("GET", "/api/teacher/status")
            status_map = status_res.json() if status_res and status_res.status_code == 200 else {}
            dashboard_col.controls.clear()
            
            # Validar que tengamos listas base
            if not state["students"]:
                dashboard_col.controls.append(ft.Text("No hay estudiantes registrados.", color=COLORES["subtitulo"]))
                page.update(); return

            # 1. Procesar quién ha hecho qué (Crear un set de pares únicos: "email+tarea")
            # Esto cumple tu requerimiento: "por lo minimo haya un registro en la BD"
            actividad_registrada = set()
            data = state.get("dashboard_data", {})
            
            # Revisar respuestas
            for r in data.get("respuestas", []):
                actividad_registrada.add((r["correo"], r["practica"]))
            # Revisar chats (opcional, si contar chat cuenta como intento)
            for c in data.get("chats", []):
                actividad_registrada.add((c["correo"], c["practica"]))
            
            # 2. Construir Grid de Estudiantes ("Figuritas")
            grid = ft.GridView(
                expand=True,
                runs_count=5,          # Cuantas columnas quieres (ajusta según necesites)
                max_extent=250,        # Ancho máximo de la tarjeta
                child_aspect_ratio=0.8, # Relación aspecto (más alto que ancho)
                spacing=15,
                run_spacing=15,
            )

            # Normalizar lista de ejercicios (por si el backend manda strings o dicts)
            safe_exercises = []
            for item in state["my_exercises"]:
                if isinstance(item, str):
                    safe_exercises.append({"filename": item, "title": item})
                else:
                    safe_exercises.append(item)

            for stu in state["students"]:
                # Lista de tareas para este estudiante específico
                current_color_name = status_map.get(stu, "green")
                task_items = []
                completed_count = 0
                color_hex = {
                    "green": COLORES["exito"],
                    "yellow": COLORES["advertencia"],
                    "red": COLORES["error"],
                    "purple": "#9C27B0" # Disengaged
                }.get(current_color_name, COLORES["exito"])
                
                for ex in safe_exercises:
                    filename = ex["filename"]
                    title = ex.get("title", filename)
                    
                    # ¿Existe el par (estudiante, tarea) en los registros?
                    tiene_registro = (stu, filename) in actividad_registrada
                    if tiene_registro: completed_count += 1
                    
                    # Icono visual del estado
                    icon = ft.Icons.CHECK_CIRCLE if tiene_registro else ft.Icons.CIRCLE_OUTLINED
                    color = COLORES["exito"] if tiene_registro else COLORES["borde"]
                    
                    task_items.append(
                        ft.Row([
                            ft.Icon(icon, size=14, color=color),
                            ft.Text(title, size=12, color=COLORES["texto"], expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
                        ], spacing=5)
                    )

                # Tarjeta (Figurita) del Estudiante
                card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=COLORES["primario"], size=40),
                            ft.Column([
                                ft.Text(stu.split("@")[0], weight="bold", color=COLORES["primario"], size=14, no_wrap=True),
                                ft.Text(f"{completed_count}/{len(safe_exercises)} Tareas", size=10, color=COLORES["subtitulo"]),
                                ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=color_hex, size=40),
                            ], spacing=0, expand=True)
                        ], alignment=ft.MainAxisAlignment.START),
                        
                        ft.Divider(height=10, color="transparent"),
                        ft.Container(
                            content=ft.Column(task_items, spacing=5, scroll=ft.ScrollMode.AUTO),
                            expand=True, # Para que la lista ocupe el espacio restante de la tarjeta
                        )
                    ], spacing=5),
                    bgcolor=COLORES["accento"],
                    padding=15,
                    border_radius=15,
                    #border=ft.border.all(1, COLORES["borde"] if completed_count < len(safe_exercises) else COLORES["exito"]),
                    shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"]),
                    border=ft.border.all(2, color_hex)
                )
                grid.controls.append(card)
                
            dashboard_col.controls.append(grid)
            page.update()
            
        tab_dashboard = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Dashboard de Progreso", size=20, weight="bold", color=COLORES["texto"]),
                    ft.IconButton(ft.Icons.REFRESH, icon_color=COLORES["primario"], tooltip="Recargar datos", on_click=lambda e: load_full_dashboard())
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text("Vista rápida de participación por tarea", color=COLORES["subtitulo"]),
                ft.Divider(color=COLORES["borde"]),
                dashboard_col
            ], expand=True),
            padding=20
        )
        # --- ADD IN dashboard_profesor.py inside main() ---

        # 1. Define Grading Tab Layout
        grading_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def load_pending_grades():
            res = auth_request("GET", "/api/teacher/grades/pending")
            if res and res.status_code == 200:
                render_grading_view(res.json())
        
        def submit_grade(item_id, score, comment, action, dialog):
            res = auth_request("POST", "/api/teacher/grades/submit", json={
                "id": item_id,
                "score": score,
                "comment": comment,
                "action": action
            })
            if res and res.status_code == 200:
                flash("Evaluación guardada", ok=True)
                dialog.open = False
                page.update()
                load_pending_grades()
            else:
                flash("Error al guardar", ok=False)
        
        def open_grade_dialog(item):
            # Controls for editing
            score_field = ft.TextField(label="Calificación (0-10)", value=str(item['llm_score']), width=100)
            comment_field = ft.TextField(label="Comentario", value=item['llm_comment'], multiline=True)
            
            def on_approve(e):
                submit_grade(item['id'], item['llm_score'], item['llm_comment'], "approve", dlg)
                
            def on_edit_save(e):
                submit_grade(item['id'], score_field.value, comment_field.value, "edit", dlg)
        
            dlg = ft.AlertDialog(
                title=ft.Text(f"Evaluar: {item['correo']}"),
                content=ft.Column([
                    ft.Text(f"Práctica: {item['practica']} | Ej: {item['problema_id']}", size=12),
                    ft.Text("Respuesta del Estudiante:", weight="bold"),
                    ft.Container(content=ft.Text(item['respuesta']), bgcolor=COLORES["fondo"], padding=10),
                    ft.Divider(),
                    ft.Text("Sugerencia IA:", color=COLORES["primario"]),
                    score_field,
                    comment_field
                ], tight=True, width=500),
                actions=[
                    ft.TextButton("Cancelar", on_click=lambda e: setattr(dlg, 'open', False) or page.update()),
                    ft.ElevatedButton("Aprobar IA", on_click=on_approve, bgcolor=COLORES["exito"], color="white"),
                    ft.ElevatedButton("Guardar Cambios", on_click=on_edit_save, bgcolor=COLORES["boton"], color="white"),
                ]
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.update()

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
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

    page.is_alive = True
    def on_disconnect(e):
        page.is_alive = False
        print("Cliente desconectado. Deteniendo hilos.")
    page.on_disconnect = on_disconnect
    
    page.title = "Pro-Tutor - Portal Docente"
    COLORES = DARK_COLORS
    page.theme_mode = ft.ThemeMode.DARK if COLORES == DARK_COLORS else ft.ThemeMode.LIGHT
    page.bgcolor = COLORES["fondo"]
    page.padding = 0
    
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

    def flash(msg, color=COLORES["exito"]):
        snack = ft.SnackBar(ft.Text(msg, color=COLORES["fondo"]), bgcolor=color)
        page.overlay.append(snack)
        snack.open = True
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
            flash("Tu sesión ha expirado por inactividad.", COLORES["advertencia"])
            show_login()
            page.route = "/" 

    page.on_route_change = route_change
    
    def show_login():
        page.clean()
        
        email_field = ft.TextField(
            label="Correo Docente", 
            width=300,
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        pass_field = ft.TextField(
            label="Contraseña", 
            password=True, 
            width=300, 
            can_reveal_password=True,
            border_color=COLORES["primario"],
            color=COLORES["texto"],
            on_submit=lambda e: login_action(e)
        )
        
        def login_action(e):
            try:
                res = requests.post(f"{BASE}/api/teacher/login", json={
                    "email": email_field.value,
                    "password": pass_field.value
                })
                if res.status_code == 200:
                    data = res.json()
                    state["token"] = data["access_token"]
                    page.client_storage.set("teacher_token", data["access_token"])
                    reset_inactivity_timer()
                    flash(f"Bienvenido, {data.get('nombre', 'Profesor')}")
                    show_dashboard()
                else:
                    flash("Credenciales incorrectas", COLORES["error"])
            except Exception as ex:
                flash(f"Error de conexión: {ex}", COLORES["error"])

        def register_action(e):
            try:
                res = requests.post(f"{BASE}/api/teacher/register", json={
                    "email": email_field.value,
                    "password": pass_field.value
                })
                if res.status_code == 201:
                    flash("Cuenta creada. Inicia sesión.")
                else:
                    flash(res.json().get("msg", "Error"), COLORES["error"])
            except Exception as ex:
                flash(f"Error: {ex}", COLORES["error"])

        def add_opacity(hex_color, opacity):
            alpha = int(opacity * 255)
            return f"#{alpha:02x}{hex_color.lstrip('#')}"
        
        card = ft.Container(
            content=ft.Column([
                ft.Text("Acceso Docente", size=28, weight="bold", color=COLORES["texto"]),
                ft.Divider(height=20, color="transparent"),
                email_field,
                pass_field,
                ft.Divider(height=20, color="transparent"),
                ft.Column([
                    ft.ElevatedButton("Entrar", on_click=login_action, bgcolor=COLORES["boton"], color=COLORES["fondo"], width=300, height=50),
                    ft.TextButton("¿No tienes cuenta? Regístrate", on_click=register_action, style=ft.ButtonStyle(color=COLORES["primario"]), width=300)
                ], spacing=10, alignment=ft.MainAxisAlignment.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=COLORES["accento"],
            padding=40,
            border_radius=20,
            shadow=ft.BoxShadow(blur_radius=15, color=COLORES["borde"]),
            alignment=ft.alignment.center
        )
        
        layout_login = ft.Container(
            expand=True,
            image=ft.DecorationImage(
                src="/fondo_login.png",
                fit=ft.ImageFit.COVER,
            ),
            
            content=ft.Container(
                expand=True,
                #gradient=ft.LinearGradient(
                #    begin=ft.alignment.top_center,
                #    end=ft.alignment.bottom_center,
                #    colors=[add_opacity(COLORES["fondo"], 0.5), add_opacity(COLORES["fondo"], 0.8)]
                #),
                content=ft.Container(
                    content=card,
                    alignment=ft.alignment.center,
                )
            )
        )
        
        page.add(layout_login)

    def show_dashboard():
        check_session()
        page.clean()
        state["exercises"] = []

        # =========================================
        # PESTAÑA 1: Gestión de Estudiantes
        # =========================================
        new_student_mail = ft.TextField(
            hint_text="estudiante@uabc.edu.mx", 
            expand=True,
            border_color=COLORES["borde"],
            color=COLORES["texto"]
        )
        students_list_view = ft.ListView(expand=True, spacing=10)

        def load_students():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                res = requests.get(f"{BASE}/api/teacher/students", headers=headers)
                if res.status_code == 200:
                    state["students"] = res.json()
                    render_students_list()
                    update_dropdowns()
            except Exception as e:
                print(e)

        def add_student(e):
            if not new_student_mail.value: return
            e.control.disabled = True; page.update()
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                res = requests.post(f"{BASE}/api/teacher/students", headers=headers, json={"emails": [new_student_mail.value]}, timeout=10)
                if res.status_code == 200:
                    new_student_mail.value = ""
                    flash("Estudiante agegado correctamente", COLORES["exito"])
                    load_students()
                else:
                    flash("Error al agregar estudiante", COLORES["error"])
            except Exception as ex:
                flash("Error técnico", COLORES["error"])
            finally:
                e.control.disabled = False; page.update()

        def delete_student(email):
            headers = {"Authorization": f"Bearer {state['token']}"}
            res = requests.delete(f"{BASE}/api/teacher/students", headers=headers, json={"email": email})
            if res.status_code == 200:
                flash("Estudiante eliminado correctamente", COLORES["exito"])
            else:
                flash("Error al eliminar estudiante", COLORES["error"])
            load_students()

        def render_students_list():
            students_list_view.controls.clear()
            for email in state["students"]:
                students_list_view.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.PERSON, color=COLORES["primario"]),
                            ft.Text(email, expand=True, size=16, color=COLORES["texto"]),
                            ft.IconButton(ft.Icons.DELETE, icon_color=COLORES["error"], on_click=lambda e, mail=email: delete_student(mail))
                        ]),
                        bgcolor=COLORES["fondo"], padding=10, border_radius=5, border=ft.border.all(1, COLORES["borde"])
                    )
                )
            page.update()

        tab_students = ft.Container(
            content=ft.Column([
                ft.Text("Gestionar mi lista de estudiantes", size=20, weight="bold", color=COLORES["texto"]),
                ft.Text("Agregar correos de los estudiantes para monitorear su progreso", color=COLORES["subtitulo"]),
                ft.Row([new_student_mail, ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=COLORES["exito"], on_click=add_student)]),
                ft.Divider(color=COLORES["borde"]),
                students_list_view
            ]), padding=20
        )

        # =========================================
        # PESTAÑA 2: Mis Tareas
        # =========================================
        col_available = ft.ListView(expand=True, spacing=5)
        col_mine = ft.ListView(expand=True, spacing=5)

        def load_exercises():
            # Cargar mis ejercicios
            r1 = auth_request("GET", "/api/teacher/my-exercises")
            if r1 and r1.status_code == 200: state["my_exercises"] = r1.json()
            
            # Cargar todos los del server
            r2 = auth_request("GET", "/api/exercises/available")
            if r2 and r2.status_code == 200: state["all_exercises"] = r2.json()
            
            render_exercises()
            update_dropdowns()

        def add_exercise(filename):
            auth_request("POST", "/api/teacher/my-exercises", json={"filename": filename})
            flash("Tarea agregada a tu lista", COLORES["exito"])
            load_exercises()

        def remove_exercise(filename):
            auth_request("DELETE", "/api/teacher/my-exercises", json={"filename": filename})
            flash("Tarea eliminada de tu lista", COLORES["exito"])
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
            
            def create_exercise_card(ex_data, is_mine):
                minutes = ex_data.get('max_time', 0) // 60
                return ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(ex_data.get("title", "Sin Título"), weight="bold", size=16, expand=True, color=COLORES["texto"]),
                            ft.IconButton(
                                ft.Icons.DELETE if is_mine else ft.Icons.ADD_CIRCLE, 
                                icon_color=COLORES["error"] if is_mine else COLORES["exito"],
                                tooltip="Quitar" if is_mine else "Agregar", 
                                on_click=lambda e, f=ex_data["filename"]: remove_exercise(f) if is_mine else add_exercise(f)
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        
                        ft.Text(ex_data.get("description", ""), size=12, italic=True, color=COLORES["subtitulo"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        
                        ft.Container(height=5),
                        
                        ft.Row([
                            ft.Icon(ft.Icons.TIMER, size=14, color=COLORES["primario"]),
                            ft.Text(f"{minutes} min", size=12, color=COLORES["subtitulo"]),
                            ft.Container(width=10),
                            ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, size=14, color=COLORES["primario"]),
                            ft.Text(f"{ex_data.get('num_problems', 0)} ejercicios", size=12, color=COLORES["subtitulo"])
                        ])
                    ], spacing=2),
                    bgcolor=COLORES["fondo"], 
                    padding=10, 
                    border_radius=8, 
                    border=ft.border.all(1, COLORES["borde"]),
                    shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"]) 
                )

            for ex in safe_all_exercises:
                if ex["filename"] not in my_filenames:
                    col_available.controls.append(create_exercise_card(ex, False))

            for ex in safe_my_exercises:
                col_mine.controls.append(create_exercise_card(ex, True))
                
            page.update()

        tab_exercises = ft.Row([
            ft.Container(content=ft.Column([ft.Text("Catálogo global de tareas", color=COLORES["texto"]), col_available], expand=True), expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10),
            ft.Container(content=ft.Column([ft.Text("Mi lista personal de tareas", color=COLORES["texto"]), col_mine], expand=True), expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10, margin=ft.margin.only(left=10))
        ], expand=True)

        # =========================================
        # PESTAÑA 3: Monitoreo
        # =========================================
        answers_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        chats_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        
        student_filter = ft.Dropdown(
            width=400, 
            options=[ft.dropdown.Option("Todos los Estudiantes")], 
            value="Todos los Estudiantes",
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        exercise_filter = ft.Dropdown(
            width=400, 
            options=[ft.dropdown.Option("Todas las Tareas")], 
            value="Todas las Tareas",
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )

        def update_dropdowns():
            # Actualiza el filtro de estudiantes
            student_filter.options = [ft.dropdown.Option("Todos los Estudiantes")] + [ft.dropdown.Option(e) for e in state["students"]]
            
            # Actualiza el filtro de tareas
            exercise_filter.options = [ft.dropdown.Option("Todas las Tareas")] + [
                ft.dropdown.Option(key=e["filename"], text=e["title"]) for e in state["my_exercises"]
            ]
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
                flash("El mensaje no puede estar vacío", COLORES["advertencia"])
                return
            if not msg_problem_dropdown.value:
                 flash("Selecciona un número de problema", COLORES["advertencia"])
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
                flash("Mensaje enviado correctamente")
                load_data_filtered() 
            else:
                flash("Error al enviar mensaje", COLORES["error"])
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
                flash("Debes seleccionar un estudiante específico para enviar un mensaje.", COLORES["advertencia"])
                return
            if not task_filename or task_filename == "Todas las Tareas":
                flash("Debes seleccionar una tarea específica para enviar un mensaje.", COLORES["advertencia"])
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
            if student_filter.value != "Todos los Estudiantes": params["student_email"] = student_filter.value
            if exercise_filter.value != "Todas las Tareas": params["practice_name"] = exercise_filter.value
            
            res = auth_request("GET", "/api/teacher/dashboard-data", params=params)
            if res and res.status_code == 200:
                render_data(res.json())

        def render_data(data):
            answers_col.controls.clear(); chats_col.controls.clear()
            
            for r in data.get("respuestas", []):
                answers_col.controls.append(ft.Container(content=ft.Column([
                    ft.Text(f"{r['correo']} - P{r['problema_id']}", size=12, color=COLORES["primario"]),
                    ft.Text(r['respuesta'], selectable=True, color=COLORES["texto"])
                ]), bgcolor=COLORES["fondo"], padding=10, border_radius=5))

            for c in data.get("chats", []):
                role = c.get('role', 'user')
                is_bot = role == 'assistant'
                is_teacher = role == 'teacher'
                
                align = ft.CrossAxisAlignment.START if (is_bot or is_teacher) else ft.CrossAxisAlignment.END
                
                if is_teacher: 
                    bg = COLORES["secundario"]
                    txt_color = COLORES["fondo"]
                elif is_bot: 
                    bg = COLORES["borde"]
                    txt_color = COLORES["texto"]
                else: 
                    bg = COLORES["primario"]
                    txt_color = COLORES["fondo"]

                chats_col.controls.append(ft.Column([
                    ft.Text(f"{role.upper()} - {c['correo']}", size=10, color=COLORES["subtitulo"]),
                    ft.Container(content=ft.Text(c['content'], color=txt_color), bgcolor=bg, padding=10, border_radius=10)
                ], horizontal_alignment=align))
            page.update()

        # =========================================
        # NAVEGACIÓN Y CARGA INICIAL
        # =========================================
        tab_monitor = ft.Column([
            ft.Container(content=ft.Row([
                ft.Row([student_filter, exercise_filter, ft.IconButton(ft.Icons.SEARCH, on_click=load_data_filtered, icon_color=COLORES["primario"])]),
                ft.ElevatedButton("Enviar Mensaje Directo", icon=ft.Icons.SEND, bgcolor=COLORES["boton"], color=COLORES["fondo"], on_click=send_direct_message)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=10, bgcolor=COLORES["fondo"]),
            
            ft.Row([
                ft.Container(content=ft.Column([ft.Text("Respuestas", color=COLORES["texto"]), answers_col], expand=True), expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10),
                ft.Container(content=ft.Column([ft.Text("Chat", color=COLORES["texto"]), chats_col], expand=True), expand=1, bgcolor=COLORES["accento"], margin=ft.margin.only(left=10), padding=10, border_radius=10)
            ], expand=True)
        ], expand=True)

        # =========================================
        # PESTAÑA 4: Dashboard (Borrador)
        # =========================================
        dashboard_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

        def load_full_dashboard():
            # 1. Carga datos globales (sin filtros) para ver todo el panorama
            reset_inactivity_timer()
            res = auth_request("GET", "/api/teacher/dashboard-data") # Sin params trae todo
            if res and res.status_code == 200:
                state["dashboard_data"] = res.json()
                render_dashboard_view()
        
        def render_dashboard_view():
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
                task_items = []
                completed_count = 0
                
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
                            ft.Text(title, size=11, color=COLORES["texto"], expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
                        ], spacing=5)
                    )

                # Tarjeta (Figurita) del Estudiante
                card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=COLORES["primario"], size=40),
                            ft.Column([
                                ft.Text(stu.split("@")[0], weight="bold", color=COLORES["primario"], size=14, no_wrap=True),
                                ft.Text(f"{completed_count}/{len(safe_exercises)} Tareas", size=10, color=COLORES["subtitulo"])
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
                    border=ft.border.all(1, COLORES["borde"] if completed_count < len(safe_exercises) else COLORES["exito"]),
                    shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"])
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

        # Tabs Principales
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            on_change=lambda e: (
                reset_inactivity_timer(),
                load_exercises() if e.control.selected_index == 1 else None,
                load_full_dashboard() if e.control.selected_index == 3 else None
            ),
            tabs=[
                ft.Tab(text="Mis Estudiantes", content=tab_students),
                ft.Tab(text="Mis Tareas", content=tab_exercises),
                ft.Tab(text="Monitoreo", content=tab_monitor),
                ft.Tab(text="Dashboard", icon=ft.Icons.DASHBOARD, content=tab_dashboard)
            ], expand=True
        )

        page.add(ft.Row([
            ft.Text("Panel Profesor", size=20, weight="bold", color=COLORES["texto"]), 
            ft.IconButton(ft.Icons.LOGOUT, icon_color=COLORES["error"], on_click=lambda e: (page.client_storage.remove("teacher_token"), show_login()))
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), tabs)
        load_students()

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
    basedir = os.path.dirname(os.path.abspath(__file__))
    assets_path = os.path.join(basedir, "assets")
    print(f"📍 UBICACIÓN DEL SCRIPT: {basedir}")
    print(f"📂 RUTA ASSETS CALCULADA: {assets_path}")

    if os.path.exists(assets_path):
        print(f"✅ Archivos en assets: {os.listdir(assets_path)}")
    else:
        print(f"❌ LA CARPETA NO EXISTE EN: {assets_path}")

    os.environ["FLET_FORCE_WEB"] = "1"
    port = int(os.getenv("PORT", "3001"))
    
    ft.app(
        target=main, 
        view=ft.AppView.WEB_BROWSER, 
        host="0.0.0.0", 
        port=port, 
        assets_dir=assets_path
    )
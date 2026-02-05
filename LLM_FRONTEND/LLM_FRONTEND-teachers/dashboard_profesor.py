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

def main(page: ft.Page):
    page.title = "GrowTogether - Portal Docente"
    COLORES = DARK_COLORS
    page.bgcolor = COLORES["fondo"]
    page.theme_mode = ft.ThemeMode.DARK if COLORES == DARK_COLORS else ft.ThemeMode.LIGHT
    page.padding = 20
    
    # Estado Global
    state = {
        "token": page.client_storage.get("teacher_token"),
        "students": [],
        "dashboard_data": {},
        "my_exercises": [],
        "all_exercises": []
    }

    def flash(msg, color=COLORES["exito"]):
        snack = ft.SnackBar(ft.Text(msg, color=COLORES["fondo"]), bgcolor=color)
        page.overlay.append(snack)
        snack.open = True
        page.update()
    
    def check_session():
        last_heartbeat = page.client_storage.get("last_heartbeat")
        now = time.time()
        if last_heartbeat and (now - last_heartbeat > 3600): # 1 hora
            print("Sesión expirada")
            page.client_storage.remove("teacher_token")
            page.client_storage.remove("last_heartbeat")
            state["token"] = None
            show_login()
        else:
            page.client_storage.set("last_heartbeat", now)
    
    def auth_request(method, endpoint, **kwargs):
        check_session()
        if not state["token"]: return None
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {state['token']}"
        kwargs["headers"] = headers
        try:
            url = f"{BASE}{endpoint}"
            if method == "GET": return requests.get(url, **kwargs)
            if method == "POST": return requests.post(url, **kwargs)
            if method == "DELETE": return requests.delete(url, **kwargs)
        except Exception as e:
            print(f"Error request: {e}")
            return None

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
            color=COLORES["texto"]
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

        card = ft.Container(
            content=ft.Column([
                ft.Text("Acceso Docente", size=24, weight="bold", color=COLORES["texto"]),
                email_field,
                pass_field,
                ft.Row([
                    ft.ElevatedButton("Entrar", on_click=login_action, bgcolor=COLORES["boton"], color=COLORES["fondo"]),
                    ft.TextButton("Crear Cuenta", on_click=register_action, style=ft.ButtonStyle(color=COLORES["primario"]))
                ], alignment=ft.MainAxisAlignment.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
            bgcolor=COLORES["accento"],
            padding=40,
            border_radius=10,
            alignment=ft.alignment.center,
            border=ft.border.all(1, COLORES["borde"])
        )
        
        page.add(ft.Container(content=card, alignment=ft.alignment.center, expand=True))

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
            ft.Container(content=ft.Column([ft.Text("Catálogo global de tareas"), col_available], expand=True), expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10),
            ft.Container(content=ft.Column([ft.Text("Mi lista personal de tareas"), col_mine], expand=True), expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10, margin=ft.margin.only(left=10))
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
            # Actualiza el filtro de estudiantes (sin cambios)
            student_filter.options = [ft.dropdown.Option("Todos los Estudiantes")] + [ft.dropdown.Option(e) for e in state["students"]]
            
            # ACTUALIZADO: El filtro de tareas ahora usa el 'title' para mostrar y 'filename' como valor interno
            # state["my_exercises"] ahora es una lista de diccionarios, no de strings
            exercise_filter.options = [ft.dropdown.Option("Todas las Tareas")] + [
                ft.dropdown.Option(key=e["filename"], text=e["title"]) for e in state["my_exercises"]
            ]
            page.update()
            
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
                        
                        ft.Divider(height=5, color="transparent"),
                        
                        ft.Row([
                            ft.Icon(ft.Icons.TIMER, size=14, color=COLORES["primario"]),
                            ft.Text(f"{minutes} min", size=12, color=COLORES["subtitulo"]),
                            ft.Container(width=10),
                            ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, size=14, color=COLORES["primario"]),
                            ft.Text(f"{ex_data.get('num_problems', 0)} ejercicios", size=12, color=COLORES["subtitulo"])
                        ])
                    ], spacing=2),
                    bgcolor=COLORES["fondo"], 
                    padding=15, 
                    border_radius=10, 
                    border=ft.border.all(1, COLORES["borde"]),
                    shadow=ft.BoxShadow(blur_radius=5, color=COLORES["borde"]) 
                )

            for ex in safe_all_exercises:
                if ex["filename"] not in my_filenames:
                    col_available.controls.append(create_exercise_card(ex, False))

            for ex in safe_my_exercises:
                col_mine.controls.append(create_exercise_card(ex, True))
                
            page.update()

        msg_problem_id = ft.TextField(
            label="Problema número...", 
            width=100, 
            value="1", 
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        msg_text_field = ft.TextField(
            label="Escribe tu mensaje...", 
            multiline=True, 
            expand=True,
            border_color=COLORES["primario"],
            color=COLORES["texto"]
        )
        
        def close_dialog(e):
            dialog_msg.open = False
            page.update()

        def send_direct_message(e):
            # Validar selección previa
            stu = student_filter.value
            ex = exercise_filter.value
            
            if not stu or stu == "Todos los Estudiantes" or not ex or ex == "Todas las Tareas":
                flash("Selecciona un estudiante y una tarea primero.", COLORES["advertencia"])
                return

            dialog_msg.open = True
            page.update()

        def confirm_send(e):
            if not msg_text_field.value or not msg_problem_id.value: 
                flash("Escribe un mensaje y un número de problema", COLORES["advertencia"])
                return
            
            # Enviar datos explícitos al backend
            res = auth_request("POST", "/api/teacher/send-message", json={
                "student_email": student_filter.value,
                "practice_name": exercise_filter.value,
                "problema_id": int(msg_problem_id.value), # <--- ENVIAMOS EL ID MANUAL
                "message": msg_text_field.value
            })
            
            if res and res.status_code == 200:
                msg_text_field.value = ""
                dialog_msg.open = False
                flash(f"Mensaje enviado al Problema {msg_problem_id.value}")
                load_data_filtered() 
            else:
                flash("Error al enviar", COLORES["error"])
            
            page.update()

        dialog_msg = ft.AlertDialog(
            title=ft.Text("Mensaje al Estudiante"),
            content=ft.Column([
                ft.Text("Selecciona el problema destino:", size=12),
                msg_problem_id, # Campo nuevo
                msg_text_field
            ], tight=True, width=400),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dialog),
                ft.ElevatedButton("Enviar", on_click=confirm_send)
            ]
        )
        page.overlay.append(dialog_msg)

        def load_data_filtered(e=None):
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
                elif is_bot: 
                    bg = COLORES["borde"]
                else: 
                    bg = COLORES["primario"]
                
                txt_color = COLORES["fondo"] if (not is_bot) else COLORES["texto"]

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

        # Tabs Principales
        tabs = ft.Tabs(
            selected_index=0,
            on_change=lambda e: (load_exercises() if e.control.selected_index == 1 else None),
            tabs=[
                ft.Tab(text="Estudiantes", content=tab_students),
                ft.Tab(text="Mis Tareas", content=tab_exercises),
                ft.Tab(text="Monitoreo", content=tab_monitor)
            ], expand=True
        )

        page.add(ft.Row([
            ft.Text("Panel Profesor", size=20, weight="bold", color=COLORES["texto"]), 
            ft.IconButton(ft.Icons.LOGOUT, icon_color=COLORES["error"], on_click=lambda e: (page.client_storage.remove("teacher_token"), show_login()))
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), tabs)
        load_students()

    if state["token"]:
        show_dashboard()
    else:
        show_login()

if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"
    port = int(os.getenv("PORT", "3001"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
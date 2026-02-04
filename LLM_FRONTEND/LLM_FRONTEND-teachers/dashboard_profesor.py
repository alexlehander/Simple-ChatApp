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
        "dashboard_data": {}
    }

    def flash(msg, color=COLORES["exito"]):
        snack = ft.SnackBar(ft.Text(msg, color="white"), bgcolor=color)
        page.overlay.append(snack)
        snack.open = True
        page.update()

    # --- VISTAS ---

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
             # Simple registro rápido
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
                    ft.ElevatedButton("Entrar", on_click=login_action, bgcolor=COLORES["boton"], color="white"),
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

    # --- Reemplazar TODA la función show_dashboard existente ---
    def show_dashboard():
        page.clean()
        
        # Inicializar estado extra para esta vista
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
                    update_dropdowns() # Actualizar filtros
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
                    flash(f"Estudiante agregado: {res.json().get('msg')}")
                    load_students()
                else:
                    flash(f"Error: {res.json().get('msg', 'Error desconocido')}", COLORES["error"])
            except Exception as ex:
                flash(f"Error técnico: {ex}", COLORES["error"])
            finally:
                e.control.disabled = False; page.update()

        def delete_student(email):
            headers = {"Authorization": f"Bearer {state['token']}"}
            requests.delete(f"{BASE}/api/teacher/students", headers=headers, json={"email": email})
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
                ft.Text("Gestionar mi Lista de Clase", size=20, weight="bold", color=COLORES["texto"]),
                ft.Text("Agrega los correos de los estudiantes que deseas monitorear.", color=COLORES["subtitulo"]),
                ft.Row([new_student_mail, ft.IconButton(ft.Icons.ADD_CIRCLE, icon_color=COLORES["exito"], on_click=add_student)]),
                ft.Divider(color=COLORES["borde"]),
                students_list_view
            ]), padding=20
        )

        # =========================================
        # PESTAÑA 2: Mis Tareas (NUEVA)
        # =========================================
        exercises_list_view = ft.ListView(expand=True, spacing=10)

        def load_exercises():
            headers = {"Authorization": f"Bearer {state['token']}"}
            try:
                res = requests.get(f"{BASE}/api/teacher/exercises", headers=headers)
                if res.status_code == 200:
                    state["exercises"] = res.json()
                    render_exercises_list()
                    update_dropdowns() # Actualizar filtros
                else:
                    flash("No se pudieron cargar los ejercicios", COLORES["advertencia"])
            except Exception as e:
                print(f"Error loading exercises: {e}")

        def render_exercises_list():
            exercises_list_view.controls.clear()
            if not state["exercises"]:
                 exercises_list_view.controls.append(ft.Text("No se encontraron ejercicios en el servidor.", color=COLORES["subtitulo"]))
            
            for ex_name in state["exercises"]:
                exercises_list_view.controls.append(
                     ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.ASSIGNMENT, color=COLORES["secundario"]),
                            ft.Text(ex_name, expand=True, size=16, color=COLORES["texto"]),
                        ]),
                        bgcolor=COLORES["fondo"], padding=15, border_radius=5, border=ft.border.all(1, COLORES["borde"])
                    )
                )
            page.update()

        tab_exercises = ft.Container(
             content=ft.Column([
                ft.Text("Mis Tareas Disponibles", size=20, weight="bold", color=COLORES["texto"]),
                ft.Text("Estos son los ejercicios configurados en el servidor.", color=COLORES["subtitulo"]),
                ft.Divider(color=COLORES["borde"]),
                exercises_list_view
            ]), padding=20
        )

        # =========================================
        # PESTAÑA 3: Monitoreo (ACTUALIZADA)
        # =========================================
        answers_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        chats_col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
        
        # Controles de Filtro
        student_filter = ft.Dropdown(
            label="Filtrar por Estudiante", 
            width=250,
            options=[ft.dropdown.Option("todos", "Todos los Estudiantes")],
            value="todos",
            border_color=COLORES["primario"], color=COLORES["texto"]
        )
        exercise_filter = ft.Dropdown(
            label="Filtrar por Tarea", 
            width=250,
            options=[ft.dropdown.Option("todos", "Todas las Tareas")],
            value="todos",
            border_color=COLORES["primario"], color=COLORES["texto"]
        )

        def update_dropdowns():
            # Actualiza las opciones de los dropdowns basado en datos cargados
            stu_opts = [ft.dropdown.Option("todos", "Todos los Estudiantes")]
            stu_opts.extend([ft.dropdown.Option(email) for email in state["students"]])
            student_filter.options = stu_opts
            
            ex_opts = [ft.dropdown.Option("todos", "Todas las Tareas")]
            ex_opts.extend([ft.dropdown.Option(ex) for ex in state["exercises"]])
            exercise_filter.options = ex_opts
            page.update()

        def load_data_filtered(e=None):
            # Carga datos aplicando los filtros seleccionados
            headers = {"Authorization": f"Bearer {state['token']}"}
            params = {}
            
            selected_student = student_filter.value
            if selected_student and selected_student != "todos":
                params["student_email"] = selected_student
                
            selected_exercise = exercise_filter.value
            if selected_exercise and selected_exercise != "todos":
                params["practice_name"] = selected_exercise
            
            try:
                # Usamos 'params' para enviar datos en la URL (?key=val)
                res = requests.get(f"{BASE}/api/teacher/dashboard-data", headers=headers, params=params, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    render_data(data)
                    if e: flash("Datos actualizados", COLORES["exito"])
                elif res.status_code == 401:
                    state["token"] = None; show_login()
                else:
                    flash(f"Error del servidor: {res.status_code}", COLORES["error"])
            except Exception as ex:
                flash(f"Error de conexión: {ex}", COLORES["error"])

        def render_data(data):
            # Render Respuestas
            answers_col.controls.clear()
            respuestas = data.get("respuestas", [])
            if not respuestas:
                answers_col.controls.append(ft.Text("No se encontraron respuestas con los filtros actuales.", color=COLORES["subtitulo"]))
            
            for r in respuestas:
                answers_col.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(r['correo'], weight="bold", color=COLORES["primario"], size=12),
                                ft.Text(r['practica'], size=12, color=COLORES["secundario"]),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([
                                ft.Text(f"Prob ID: {r['problema_id']}", size=11, color=COLORES["subtitulo"]),
                                ft.Text(r['fecha'][:16], size=11, color=COLORES["subtitulo"])
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Divider(height=5, color="transparent"),
                            ft.Text(r['respuesta'], selectable=True, color=COLORES["texto"], size=13)
                        ]),
                        bgcolor=COLORES["fondo"], padding=15, border_radius=8, border=ft.border.all(1, COLORES["borde"])
                    )
                )

            # Render Chats (ARREGLO DEL ESPACIO MUERTO AQUI)
            chats_col.controls.clear()
            chats = data.get("chats", [])
            if not chats:
                chats_col.controls.append(ft.Text("No hay historial de chat para los filtros actuales.", color=COLORES["subtitulo"]))

            for c in chats:
                is_bot = c['role'] == 'assistant'
                align = ft.CrossAxisAlignment.START if is_bot else ft.CrossAxisAlignment.END
                color_bg = COLORES["borde"] if is_bot else COLORES["primario"]
                text_col = COLORES["texto"] if is_bot else "#FFFFFF"
                
                chats_col.controls.append(
                    ft.Column([
                        # Mostramos correo y práctica para contexto
                        ft.Text(f"{'IA Tutor' if is_bot else c['correo'][:15]+'...'} [{c.get('practica','?')}] {c['fecha'][11:16]}", size=10, color=COLORES["subtitulo"]),
                        ft.Container(
                            content=ft.Text(c['content'], size=14, color=text_col),
                            bgcolor=color_bg, padding=10, border_radius=10, 
                            # width=400  <--- ELIMINADO para que se expanda
                        )
                    ], horizontal_alignment=align)
                )
            page.update()

        tab_monitor = ft.Container(
            content=ft.Column([
                # Fila de Filtros
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FILTER_ALT, color=COLORES["primario"]),
                        student_filter,
                        exercise_filter,
                        ft.ElevatedButton("Filtrar Resultados", icon=ft.Icons.SEARCH, on_click=load_data_filtered, bgcolor=COLORES["boton"], color="white")
                    ], wrap=True, spacing=15),
                    padding=10, bgcolor=COLORES["fondo"], border_radius=10, border=ft.border.all(1, COLORES["borde"])
                ),
                ft.Divider(color="transparent", height=10),
                # Columnas de Datos
                ft.Expanded(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Respuestas Entregadas", size=18, weight="bold", color=COLORES["texto"]),
                                answers_col
                            ], expand=True),
                            expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10
                        ),
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Feed de Conversaciones", size=18, weight="bold", color=COLORES["texto"]),
                                chats_col
                            ], expand=True),
                            expand=1, bgcolor=COLORES["accento"], padding=10, border_radius=10, margin=ft.margin.only(left=10)
                        )
                    ], expand=True)
                )
            ]),
            padding=20, expand=True
        )

        # =========================================
        # NAVEGACIÓN Y CARGA INICIAL
        # =========================================
        def on_tab_change(e):
            idx = e.control.selected_index
            if idx == 1: # Pestaña Tareas
                 load_exercises()
            elif idx == 2: # Pestaña Monitoreo
                 # Cargar datos con filtros actuales (o iniciales "todos")
                 load_data_filtered()

        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Mis Estudiantes", icon=ft.Icons.PEOPLE, content=tab_students),
                ft.Tab(text="Mis Tareas", icon=ft.Icons.ASSIGNMENT, content=tab_exercises), # Nueva Pestaña
                ft.Tab(text="Monitoreo", icon=ft.Icons.MONITOR_HEART, content=tab_monitor),
            ],
            expand=True,
            on_change=on_tab_change,
            label_color=COLORES["primario"],
            unselected_label_color=COLORES["subtitulo"],
            indicator_color=COLORES["primario"]
        )

        logout_btn = ft.IconButton(
            ft.Icons.LOGOUT, 
            tooltip="Cerrar Sesión", 
            icon_color=COLORES["error"],
            on_click=lambda e: (page.client_storage.remove("teacher_token"), show_login())
        )
        
        page.add(
            ft.Row([
                ft.Text("Panel Profesor", size=20, weight="bold", color=COLORES["texto"]), 
                logout_btn
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            tabs
        )
        
        # Carga inicial de datos esenciales
        load_students()
        load_exercises() # Cargar ejercicios para llenar el dropdown de filtros

    if state["token"]:
        show_dashboard()
    else:
        show_login()

if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"
    port = int(os.getenv("PORT", "3001"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
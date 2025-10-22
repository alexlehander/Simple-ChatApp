import flet as ft
import requests
import time
import threading
import os

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
BACKEND_URL_OBTENER_PROBLEMA  = f"{BASE}/obtener_problema"

# ---- Persistence helpers (top of file) ----
STATE_KEYS = {
    "screen": "ui_screen",                     # "consent", "instructions", "survey", "problems", "final"
    "code": "correo_identificacion",           # you already use this key
    "current_problem": "current_problem_id",   # int
    "answers": "answers_map",                  # dict: {problem_id: "answer text"}
    "chat": "chat_map",                        # dict: {problem_id: [{"role":"user|agent","text":"..."}]}
    "timer_start": "timer_start_epoch",        # int epoch seconds when 120min started
}

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
    page.horizontal_alignment = "center"
    page.vertical_alignment = "center"
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
    
    page.overlay.append(save_snack)
    
    # =============== PANTALLA 1: CONSENTIMIENTO =============== 
    def mostrar_pantalla_consentimiento():
        save_k(page, STATE_KEYS["screen"], "consent")
        page.scroll = ft.ScrollMode.ALWAYS
        
        title = ft.Text(
            "¿Listo(a) para resolver la Práctica 4 de la clase de Análisis de Algoritmos con ayuda de un simple y sencillo prototipo de un tutor inteligente?",
            size=24, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER,
        )
        
        subtitle = ft.Text(
            "Puedes usar tus apuntes (texto o digital) así como realizar búsqueda en el navegador. Ten cuidado de no cerrar la ventana del tutor inteligente. Tienes prohibido usar chatbots (ChatGPT, LLaMa, etc.) o platicar con tus compañeros.",
            size=20, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        
        details = ft.Text(
            "Se van a recolectar datos relacionados con tu solución de la práctica, NO se va a recolectar información personal.",
            size=16, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        
        aceptar_btn = ft.ElevatedButton(
            "Continuar",
            disabled=True,
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=lambda e: mostrar_pantalla_instrucciones(),
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
    def mostrar_pantalla_instrucciones():
        save_k(page, STATE_KEYS["screen"], "instructions")
        page.vertical_alignment = ft.CrossAxisAlignment.START
        page.scroll = ft.ScrollMode.ALWAYS
        
        titulo = ft.Text(
            "Instrucciones",
            size=24, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER,
        )
        
        cuerpo = ft.Text(
            "Si deseas consultar un instructivo audiovisual sobre la interfaz de usuario de esta práctica, puedes ver este video (OJO no representa la intervención experimental actual).",
            size=20, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        
        continuar = ft.ElevatedButton(
            "Continuar",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=lambda e: mostrar_pantalla_encuesta(),
        )
        
        list_view = ft.ListView(
            controls=[
                titulo, ft.Divider(20),
                cuerpo, ft.Divider(20),
                ft.Row([continuar], alignment=ft.MainAxisAlignment.CENTER),
            ],
            expand=True,
            spacing=20,
            padding=20
        )
        
        container = ft.Container(
            content=list_view,
            padding=0,
            bgcolor=COLORES["accento"],
            border_radius=10,
            shadow=ft.BoxShadow(blur_radius=10, color=COLORES["borde"]),
            width=600,
        )
        
        page.clean(); page.add(container)
        
    # =============== PANTALLA 3: ENCUESTA + CÓDIGO =============== 
    def mostrar_pantalla_encuesta():
        save_k(page, STATE_KEYS["screen"], "survey")
        
        email_input = ft.TextField(
            label=ft.Container(
                content=ft.Text("Correo institucional (Google)", text_align=ft.TextAlign.CENTER),
                alignment=ft.alignment.center
            ),
            hint_text="nombre@uabc.edu.mx",
            width=400,
            text_align=ft.TextAlign.CENTER,
            color=COLORES["texto"],
            bgcolor=COLORES["accento"],
            border_color=COLORES["borde"],
        )
        
        def guardar_email(e):
            correo = email_input.value.strip()
            if "@" not in correo:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Ingresa un correo válido", color=COLORES["accento"]),
                    bgcolor=COLORES["error"], open=True, duration=2000
                )
                page.update()
                return
            page.client_storage.set("correo_identificacion", correo)
            mostrar_pantalla_intervencion()
            
        continuar_btn = ft.ElevatedButton(
            "Continuar",
            bgcolor=COLORES["boton"],
            color=COLORES["texto"],
            on_click=guardar_email,
        )
        
        layout = ft.Column(
            [
                ft.Text("Inicia sesión con tu correo Google institucional", size=22, weight="bold", color=COLORES["primario"]),
                email_input,
                continuar_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        )
        
        page.clean()
        page.add(ft.Container(content=layout, padding=30, bgcolor=COLORES["accento"], border_radius=10))
        
        # =============== PANTALLA 4: INTERVENCIÓN (CHAT + PROBLEMAS) ===============
    def mostrar_pantalla_intervencion():
        save_k(page, STATE_KEYS["screen"], "problems")

        # Código visible
        correo = page.client_storage.get("correo_identificacion") or "No disponible"
        correo_texto_visible = ft.Text(
            f"Correo: {correo}",
            size=22, weight="bold", color=COLORES["subtitulo"],
            text_align=ft.TextAlign.CENTER
        )

        stop_timer = False
        problema_actual_id = 1
        
        def get_total_problems():
            try:
                r = requests.get(f"{BASE}/contar_problemas", timeout=5)
                total = int(r.json().get("total", 0))
                if total > 0:
                    return total
            except Exception:
                pass

            # Fallback: probe sequentially until 404, max 200 problems
            total = 0
            for i in range(1, 201):
                try:
                    r = requests.get(f"{BACKEND_URL_OBTENER_PROBLEMA}/{i}", timeout=3)
                    if r.status_code != 200:
                        break
                    total = i
                except Exception:
                    break
            return max(total, 1)

        NUM_PROBLEMAS = get_total_problems()

        # --- Align completion flags length with current total ---
        prev = load_k(page, "respuestas_enviadas", [])
        if not isinstance(prev, list) or len(prev) != NUM_PROBLEMAS:
            respuestas_enviadas = [False] * NUM_PROBLEMAS
        else:
            respuestas_enviadas = prev
        save_k(page, "respuestas_enviadas", respuestas_enviadas)

        def guardar_respuesta_actual():
            #Guarda el texto actual antes de cambiar de problema.
            if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                texto = (respuesta_container.controls[0].value or "").strip()
                save_k(page, f"respuesta_{problema_actual_id}", texto)

        #def guardar_chat_actual():
        #    """Guarda el chat actual asociado al problema."""
        #    mensajes = []
        #    for c in chat_area.controls:
        #        if isinstance(c, ft.Row) and c.controls:
        #            txts = c.controls[0].content
        #            if isinstance(txts, ft.Text):
        #                mensajes.append({"role": "assistant", "text": txts.value})
        #    if mensajes:
        #        update_map(page, STATE_KEYS["chat"], problema_actual_id, mensajes)

        def cargar_chat_guardado(id_problema):
            #Recupera el historial del chat de un problema.
            chat_area.controls.clear()
            chats = load_k(page, STATE_KEYS["chat"], {})
            for msg in chats.get(str(id_problema), []):
                align = ft.MainAxisAlignment.END if msg["role"] == "user" else ft.MainAxisAlignment.START
                bubble_color = COLORES["boton"] if msg["role"] == "user" else COLORES["accento"]
                chat_area.controls.append(
                    ft.Row([
                        ft.Container(
                            content=ft.Text(msg["text"], color=COLORES["texto"], size=16),
                            bgcolor=bubble_color,
                            padding=10,
                            border_radius=10,
                            width=350
                        )
                    ], alignment=align)
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
            # ✅ ensure buttons are re-enabled on each new problem
            siguiente_button.disabled = False
            page.update()

            page._is_loading_problem = True
            try:
                r = requests.get(f"{BACKEND_URL_OBTENER_PROBLEMA}/{id_problema}")
                if r.status_code == 200:
                    p = r.json()
                    ejercicio_text.value = p.get("enunciado", "")
                    ejercicio_text.text_align = ft.TextAlign.CENTER

                    respuesta_container.controls.clear()
                    tf = ft.TextField(
                        hint_text="Escribe tu respuesta aquí",
                        expand=True, multiline=True, min_lines=1, max_lines=15,
                        bgcolor=COLORES["secundario"], border_color=COLORES["secundario"],
                        focused_border_color=COLORES["primario"], border_radius=15,
                        hint_style=ft.TextStyle(color=COLORES["accento"]),
                        on_change=lambda e: save_k(page, f"respuesta_{id_problema}", e.control.value)
                    )

                    # 🟢 Restore saved draft
                    draft = page.client_storage.get(f"respuesta_{id_problema}")
                    if draft:
                        tf.value = draft

                    respuesta_container.controls.append(tf)
                    feedback_text.value = ""
                    status_row.visible = False

                    # (opcional) si antes hubo error de backend, limpia el flag
                    if getattr(page, "_backend_error_reported", False):
                        page._backend_error_reported = False
                else:
                    feedback_text.value = "Error al cargar el problema."
                    feedback_text.color = COLORES["error"]

            except Exception as e:
                if not getattr(page, "_backend_error_reported", False):
                    feedback_text.value = "Error de conexión con el servidor."
                    feedback_text.color = COLORES["error"]
                    page._backend_error_reported = True  # evita spam de errores
                print(f"[WARN] Connection error: {type(e).__name__}")

            finally:
                # ✅ siempre liberar el flag y actualizar UI
                page._is_loading_problem = False
                cargar_chat_guardado(id_problema)
                numero_text.value = f"Problema: {id_problema} de {NUM_PROBLEMAS}"
                estado = "✅ Entregado" if respuestas_enviadas[id_problema - 1] else "⏳ Pendiente"
                estado_text.value = f"Estado: {estado}"
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Entregados: {entregados} de {NUM_PROBLEMAS}"
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
                    mostrar_pantalla_encuesta_final()
                else:
                    feedback_text.value = "¡Aún tienes problemas pendientes por contestar antes de finalizar!"
                    feedback_text.color = COLORES["advertencia"]
                    page.update()
                return

            cargar_problema(nuevo_id)

        def enviar_respuesta(e):
            if getattr(page, "_is_sending_response", False):
                return
            page._is_sending_response = True
            nonlocal problema_actual_id, stop_timer
            siguiente_button.disabled = True
            page.update()

            try:
                val = ""
                if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                    val = (respuesta_container.controls[0].value or "").strip()
                if not val:
                    feedback_text.value = "La respuesta no puede estar vacía."
                    feedback_text.color = COLORES["error"]
                    siguiente_button.disabled = False
                    page.update()
                    return

                resp = requests.post(
                    f"{BACKEND_URL_VERIFICAR}/{problema_actual_id}",
                    json={"respuesta": val, "correo_identificacion": correo},
                )
                resp.raise_for_status()

                # ✅ Guardar y avanzar de forma segura
                save_k(page, f"respuesta_{problema_actual_id}", val)
                respuestas_enviadas[problema_actual_id - 1] = True
                save_k(page, "respuestas_enviadas", respuestas_enviadas)
                # 🔄 Refrescar rótulos de Estado / Progreso
                estado_text.value = "Estado: ✅ Entregado"
                entregados = sum(1 for x in respuestas_enviadas if x)
                progreso_text.value = f"Entregados: {entregados} de {NUM_PROBLEMAS}"
                feedback_text.value = ""
                save_snack.open = True
                status_icon.visible = True
                status_text.value = "Guardado"
                status_row.visible = True
                page.update()
                threading.Timer(1.2, lambda: (setattr(status_row, "visible", False), page.update())).start()

                # --- Verificar existencia del siguiente problema ---
                next_id = problema_actual_id + 1
                r = requests.get(f"{BACKEND_URL_OBTENER_PROBLEMA}/{next_id}", timeout=10)
                if r.status_code == 200:
                    save_k(page, STATE_KEYS["current_problem"], next_id)
                    cargar_problema(next_id)
                else:
                    # No navegamos a la encuesta final desde "Enviar", Solo informamos que no hay más problemas para cargar.
                    feedback_text.value = "¡Este fue el último problema disponible, presiona «Siguiente» para finalizar si ya entregaste todo!"
                    feedback_text.color = COLORES["advertencia"]
                    siguiente_button.disabled = False
                    page.update()

            except Exception:
                feedback_text.value = "Error al registrar o cargar el siguiente problema."
                feedback_text.color = COLORES["error"]
                siguiente_button.disabled = False
                page.update()
            finally:
                # ✅ Siempre desbloquear
                page._is_sending_response = False

        # ---- Chat UI ----
        chat_area = ft.ListView(expand=True, spacing=10, auto_scroll=False, padding=10)
        
        chat_container = ft.Container(
            content=chat_area, padding=10, bgcolor=COLORES["accento"],
            height=400, border_radius=8, expand=True
        )

        def send_message(e):
            msg = (user_input.value or "").strip()
            if not msg:
                chat_area.controls.append(
                    ft.Container(
                        content=ft.Text("Por favor, escribe un mensaje", color=COLORES["error"], size=16),
                        padding=10, bgcolor=ft.colors.RED_50, border_radius=5,
                        alignment=ft.alignment.center_right,
                    )
                )
                page.update()
                return

            # Show user bubble
            chat_area.controls.append(
                ft.Row(
                    [ft.Container(
                        content=ft.Text(f"{msg}", color=COLORES["texto"], size=16),
                        bgcolor=COLORES["boton"],
                        padding=10, border_radius=10,
                        alignment=ft.alignment.center_right, width=200
                    )],
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
                    json={"message": msg, "correo_identificacion": correo},
                    timeout=30,
                )
                data = r.json() if r.ok else {"response": "Sin respuesta"}
                chat_area.controls.append(
                    ft.Row(
                        [ft.Container(
                            content = ft.Text(f"{data.get('response','Sin respuesta')}", color=COLORES["texto"], size=16),
                            bgcolor=COLORES["accento"],
                            padding=10,
                            border_radius=10,
                            alignment=ft.alignment.center_left,
                            width=400
                        )],
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
                            content=ft.Text("Error de conexión con el servidor."),
                            bgcolor = COLORES["error"],
                            color = COLORES["accento"],
                            padding=10,
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
            expand=True,
            bgcolor=COLORES["secundario"],
            border_color=COLORES["secundario"],
            focused_border_color=COLORES["primario"],
            border_radius=15,
            hint_style=ft.TextStyle(color=COLORES["accento"]),
            max_length=500,
            on_submit=send_message,
        )

        # ---- Problem area ----
        ejercicio_text = ft.Text("Aquí aparecerá el enunciado del problema", size=20, color=COLORES["primario"], weight="bold")
        respuesta_container = ft.Column(spacing=10)
        feedback_text = ft.Text("", size=16, color=COLORES["exito"])
        status_icon = ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=COLORES["exito"], size=18, visible=False)
        status_text = ft.Text("", size=12, color=COLORES["exito"])
        status_row = ft.Row([status_icon, status_text], spacing=6, visible=False)

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
        
        # (opcional) pre-inicializar antes del primer cargar_problema:
        estado_text.value = "Estado: ⏳ Pendiente"
        progreso_text.value = f"Entregados: {sum(1 for x in respuestas_enviadas if x)} de {NUM_PROBLEMAS}"
        
        problemas_container = ft.Container(
            content=ft.Column(
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
                alignment=ft.MainAxisAlignment.START,
                spacing=15,
                expand=True,
            ),
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            expand=True,
        )

        # Layout
        temporizador_text = ft.Text("20:00", size=32, color=COLORES["primario"], weight="bold", text_align=ft.TextAlign.CENTER)
        main_row = ft.Row([
            ft.Column([
                chat_container,
                user_input
            ], spacing=15, expand=True),
            problemas_container
        ], spacing=20, expand=True)
        
        def reiniciar_practica(e):
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
                shape=ft.RoundedRectangleBorder(radius=6),
            )
        )
        
        # Layout principal con el botón de reinicio en la esquina
        header_row = ft.Row(
            [correo_texto_visible, reiniciar_button],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

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
        
        # Temporizador (120min)
        def iniciar_temporizador():
            nonlocal stop_timer
            start_epoch = load_k(page, STATE_KEYS["timer_start"], None)
            now = int(time.time())
            if start_epoch is None:
                start_epoch = now
                save_k(page, STATE_KEYS["timer_start"], start_epoch)

            TOTAL_SECONDS = 120 * 60
            elapsed = max(0, now - int(start_epoch))
            remaining = max(0, TOTAL_SECONDS - elapsed)

            def cuenta():
                # ✅ skip updates while page is rebuilding
                while getattr(page, "_is_loading_problem", False):
                    time.sleep(0.1)
                t = remaining
                while t > 0 and not stop_timer:
                    m, s = divmod(t, 60)
                    temporizador_text.value = f"{m:02}:{s:02}"
                    page.update(); time.sleep(1); t -= 1
                if not stop_timer:
                    temporizador_text.value = "¡Tiempo terminado!"
                    siguiente_button.disabled = True
                    page.update()

                    # ✅ Schedule UI change safely on main thread
                    def _show_final():
                        page.invoke_later(lambda: mostrar_pantalla_encuesta_final())

                    threading.Timer(3, _show_final).start()

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
            "Después de terminar los problemas, te agradecería mucho que respondieras el siguiente cuestionario, ya que es muy importante conocer tu experiencia con el sistema. Por favor, copia y pega tu código de identificación en esta última encuesta. Al finalizarla, habrás completado tu participación en el estudio y podrás cerrar todas las pestañas utilizadas. Si leiste este mensaje con atencion, mandame un correo con el mensaje secreto 'quiero 10' y tendras 10 sobre 100 puntos extras en esta practica.",
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
            "Cuestionario Final",
            url="https://docs.google.com/forms/d/e/1FAIpQLScX0lriSeCq6YdRYQnOjHVV12x6IQX52eULPGObiaC5LGmi8g/viewform?usp=dialog",
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
        page.add(
            ft.Column(
                [container,
                ft.Row([reiniciar_button_final], alignment=ft.MainAxisAlignment.END)],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            )
        )

    # Boot
    screen = load_k(page, STATE_KEYS["screen"], "consent")
    if screen == "instructions":
        mostrar_pantalla_instrucciones()
    elif screen == "survey":
        mostrar_pantalla_encuesta()
    elif screen == "problems":
        mostrar_pantalla_intervencion()
    elif screen == "final":
        mostrar_pantalla_encuesta_final()
    else:
        mostrar_pantalla_consentimiento()


if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"  # 👈 forces web mode instead of desktop
    port = int(os.getenv("PORT", "3000"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
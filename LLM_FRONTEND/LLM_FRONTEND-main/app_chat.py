import flet as ft
import requests
import time
import threading
import os
import random
import string

# ========= Config / Colors =========
COLORES = {
    "fondo": "#b6f0cc",
    "primario": "#0e3a2d",
    "secundario": "#7dd1a3",
    "accento": "#b7e4c7",
    "texto": "#1a3a32",
    "subtitulo": "#5a7c6e",
    "boton": "#0e3a2d",
    "borde": "#c8e6d5",
    "error": "#e57373",
    "exito": "#81c784",
}

BASE = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
BACKEND_URL_GENERAR_CODIGO    = f"{BASE}/generar_codigo"
BACKEND_URL_CHAT              = f"{BASE}/chat"
BACKEND_URL_VERIFICAR         = f"{BASE}/verificar_respuesta"
BACKEND_URL_OBTENER_PROBLEMA  = f"{BASE}/obtener_problema"


def main(page: ft.Page):
    page.title = "Grow Together"
    page.horizontal_alignment = "center"
    page.vertical_alignment = "center"
    page.padding = 20
    page.bgcolor = COLORES["fondo"]

    page.theme = ft.Theme(
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color={"default": ft.colors.BLACK},
            track_color={"default": ft.colors.BLACK12},
            thickness=10,
            radius=10,
        )
    )

    # Global snack (Saved)
    save_snack = ft.SnackBar(content=ft.Text("Respuesta guardada"), open=False, duration=1000)
    page.overlay.append(save_snack)

    # =============== PANTALLA 1: CONSENTIMIENTO ===============
    def mostrar_pantalla_consentimiento():
        page.scroll = ft.ScrollMode.ALWAYS
        title = ft.Text("¿Listo(a) para resolver la Práctica 4 de la clase de Análisis de Algoritmos con ayuda de un simple y sencillo prototipo de un ayudante inteligente?", size=24, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER)
        subtitle = ft.Text(
            "Te recuerdo que puedes usar tus apuntes (texto o digital) así como realizar búsqueda en el navegador. Ten cuidado de no cerrar la ventana del tutor inteligente. Tienes prohibido usar chatbots y platicar con tus compañeros :)",
            size=18, color=COLORES["texto"], text_align=ft.TextAlign.CENTER,
        )
        details = ft.Text(
            "Se recabarán datos relacionados con la solución de la práctica, NO se recabarán datos personales.",
            size=16, color=COLORES["subtitulo"], text_align=ft.TextAlign.JUSTIFY,
        )
        thanks = ft.Text("¡Gracias por tu participación!", size=16, color=COLORES["subtitulo"], text_align=ft.TextAlign.CENTER)

        aceptar_btn = ft.ElevatedButton("Aceptar y continuar", disabled=True, bgcolor=COLORES["boton"], color=ft.colors.WHITE, on_click=lambda e: mostrar_pantalla_instrucciones())

        def on_check(e):
            aceptar_btn.disabled = not e.control.value
            page.update()

        checkbox = ft.Checkbox(
            label="¡Vamos a resolver la práctica!", on_change=on_check,
            active_color=ft.colors.BLACK, check_color=ft.colors.WHITE, fill_color=ft.colors.BLACK,
            overlay_color=ft.colors.BLACK12, label_style=ft.TextStyle(color=COLORES["primario"])
        )

        layout = ft.Column(
            [title, ft.Divider(20), subtitle, ft.Divider(20), details, ft.Divider(20), checkbox, ft.Divider(20), thanks, ft.Divider(30), aceptar_btn],
            alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20,
        )
        container = ft.Container(
            content=ft.Column([layout], scroll=ft.ScrollMode.ALWAYS, expand=True),
            padding=20, bgcolor=COLORES["accento"], border_radius=10, shadow=ft.BoxShadow(blur_radius=10, color=ft.colors.GREY_400), width=600, expand=True,
        )
        page.clean(); page.add(container)

    # =============== PANTALLA 2: INSTRUCCIONES ===============
    def mostrar_pantalla_instrucciones():
        page.vertical_alignment = ft.CrossAxisAlignment.START
        page.scroll = ft.ScrollMode.ALWAYS

        titulo = ft.Text("Instrucciones", size=24, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER)
        cuerpo = ft.Text(
            "Si deseas consultar un instructivo audiovisual sobre la interfaz de usuario de esta práctica, puedes ver este video (OJO no representa la intervención experimental actual).",
            size=16, color=COLORES["texto"], text_align=ft.TextAlign.JUSTIFY,
        )
        boton_video = ft.TextButton(
            "Ir a video", url="https://drive.google.com/file/d/1QP8gERIQeL3u8Pnlehe9yrcN_upW_dWL/view?usp=sharing",
            style=ft.ButtonStyle(color=ft.colors.WHITE, bgcolor=COLORES["boton"], padding=ft.padding.symmetric(20, 10), shape=ft.RoundedRectangleBorder(radius=8)),
        )
        continuar = ft.ElevatedButton("Continuar", on_click=lambda e: mostrar_pantalla_encuesta(), bgcolor=COLORES["boton"], color=ft.colors.WHITE)

        list_view = ft.ListView(controls=[titulo, ft.Divider(20), cuerpo, ft.Divider(30), ft.Row([boton_video], alignment=ft.MainAxisAlignment.CENTER), ft.Row([continuar], alignment=ft.MainAxisAlignment.CENTER)], expand=True, spacing=10, padding=20)
        container = ft.Container(content=list_view, padding=0, bgcolor=COLORES["accento"], border_radius=10, shadow=ft.BoxShadow(blur_radius=10, color=ft.colors.GREY_400), width=600)
        page.clean(); page.add(container)

    # =============== PANTALLA 3: ENCUESTA + CÓDIGO ===============
    def mostrar_pantalla_encuesta():
        # obtiene/genera código
        codigo_generado = "ERROR"
        try:
            r = requests.get(BACKEND_URL_GENERAR_CODIGO)
            if r.status_code == 200:
                codigo_generado = r.json().get("codigo", "ERROR")
                page.client_storage.set("codigo_identificacion", codigo_generado)
        except Exception:
            pass

        codigo_text = ft.Text("Utiliza el siguiente código de identificación para ingresar al cuestionario:", size=18, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER)

        def copiar_codigo(e):
            page.set_clipboard(codigo_generado)
            page.snack_bar = ft.SnackBar(ft.Text("Código copiado al portapapeles"), open=True)
            page.update()

        codigo_btn = ft.TextButton(
            content=ft.Text(codigo_generado, size=26, weight="bold", color=ft.colors.BLACK, text_align=ft.TextAlign.CENTER),
            on_click=copiar_codigo,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(20, 10), side=ft.BorderSide(1.5, COLORES["boton"]), shape=ft.RoundedRectangleBorder(radius=8), bgcolor=ft.colors.WHITE),
        )

        instruccion = ft.Text(
            "Por favor, copia y pega este código identificador en todos los formularios que aparecerán posteriormente. Al terminar de contestar el cuestionario regresa al sistema para iniciar los problemas matemáticos. Como apoyo en la resolución de los problemas, puedes usar tanto la calculadora de tu computadora como el agente.",
            size=16, color=COLORES["texto"], text_align=ft.TextAlign.JUSTIFY,
        )

        link_encuesta = ft.TextButton("Encuesta Demográfica", url="https://docs.google.com/forms/d/e/1FAIpQLScHqD8lG-_kG1P9sJU-tHxP3KHO0bSEgXKMdcoILb8lvzi0Wg/viewform?usp=dialog", style=ft.ButtonStyle(color=ft.colors.WHITE, bgcolor=COLORES["boton"], padding=ft.padding.symmetric(20, 10), shape=ft.RoundedRectangleBorder(radius=8)))
        iniciar_btn = ft.ElevatedButton("Iniciar problemas matemáticos", on_click=lambda e: pasar_a_problemas(), bgcolor=COLORES["boton"], color=ft.colors.WHITE, disabled=True)
        temporizador_text = ft.Text("05:00", size=24, color=COLORES["primario"], weight="bold", text_align=ft.TextAlign.CENTER)

        def iniciar_temporizador():
            def cuenta():
                t = 30  # seg (ajustable)
                while t > 0:
                    m, s = divmod(t, 60)
                    temporizador_text.value = f"{m:02}:{s:02}"
                    page.update(); time.sleep(1); t -= 1
                iniciar_btn.disabled = False
                temporizador_text.value = "¡Tiempo terminado!"; page.update()
            threading.Thread(target=cuenta, daemon=True).start()
        iniciar_temporizador()

        layout = ft.Column([codigo_text, codigo_btn, ft.Divider(10), instruccion, ft.Divider(20), link_encuesta, ft.Divider(20), temporizador_text, iniciar_btn], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20)
        container = ft.Container(content=layout, padding=30, bgcolor=COLORES["accento"], border_radius=10, shadow=ft.BoxShadow(blur_radius=10, color=ft.colors.GREY_400), width=600)
        page.clean(); page.add(container)

    def pasar_a_problemas():
        mostrar_pantalla_intervencion()

    # =============== PANTALLA 4: INTERVENCIÓN (CHAT + PROBLEMAS) ===============
    def mostrar_pantalla_intervencion():
        # Código visible
        codigo = page.client_storage.get("codigo_identificacion") or "No disponible"
        codigo_texto_visible = ft.Text(f"Código de identificación: {codigo}", size=22, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER)

        stop_timer = False
        respuestas_usuario = [None] * 18
        problema_actual_id = 1

        # ---- Chat ----
        chat_area = ft.ListView(expand=True, spacing=10, auto_scroll=False, padding=10)
        chat_container = ft.Container(content=chat_area, padding=10, bgcolor=COLORES["secundario"], height=400, border_radius=8, expand=True)
        user_input = ft.TextField(hint_text="Escribe tu mensaje...", expand=True, color=ft.colors.WHITE, bgcolor=COLORES["secundario"], border_color=COLORES["borde"], focused_border_color=COLORES["primario"], border_radius=15, hint_style=ft.TextStyle(color=ft.colors.WHITE), max_length=500)
        send_button = ft.ElevatedButton(text="Enviar", icon=ft.icons.SEND, bgcolor=COLORES["boton"], color=ft.colors.WHITE)

        def send_message(e):
            msg = (user_input.value or "").strip()
            if not msg:
                chat_area.controls.append(ft.Container(content=ft.Text("Por favor, escribe un mensaje.", color=COLORES["error"]), padding=10, bgcolor=ft.colors.RED_50, border_radius=5, alignment=ft.alignment.center_right))
                page.update(); return
            chat_area.controls.append(ft.Row([ft.Container(content=ft.Text(f"Usuario: {msg}", color=ft.colors.WHITE), padding=10, bgcolor=COLORES["boton"], border_radius=10, alignment=ft.alignment.center_right, width=200)], alignment=ft.MainAxisAlignment.END))
            user_input.value = ""; page.update()
            try:
                r = requests.post(f"{BACKEND_URL_CHAT}/{problema_actual_id}", json={"message": msg, "codigo_identificacion": codigo})
                data = r.json()
                chat_area.controls.append(ft.Row([ft.Container(content=ft.Text(f"Agente: {data.get('response', 'Sin respuesta')}", color=ft.colors.BLACK), padding=10, bgcolor="#d4edda", border_radius=10, alignment=ft.alignment.center_left, width=400)], alignment=ft.MainAxisAlignment.START))
            except Exception:
                chat_area.controls.append(ft.Row([ft.Container(content=ft.Text("Error de conexión con el servidor.", color=COLORES["error"]), padding=10, bgcolor=ft.colors.RED_100, border_radius=10)], alignment=ft.MainAxisAlignment.START))
            page.update()
        send_button.on_click = send_message

        chat_box = ft.Column([chat_container, ft.Row([user_input, send_button], spacing=10)], spacing=10, expand=True)

        # ---- Problemas ----
        ejercicio_text = ft.Text("Aquí aparecerá el enunciado del problema", size=20, color=COLORES["primario"], weight="bold")
        respuesta_container = ft.Column(spacing=10)
        feedback_text = ft.Text("", size=16, color=COLORES["exito"])
        # status flash
        status_icon = ft.Icon(ft.icons.CHECK_CIRCLE_OUTLINE, color=ft.colors.GREEN_400, size=18, visible=False)
        status_text = ft.Text("", size=12, color=ft.colors.GREEN_400)
        status_row = ft.Row([status_icon, status_text], spacing=6, visible=False)

        siguiente_button = ft.ElevatedButton("Siguiente problema", icon=ft.icons.CHEVRON_RIGHT, bgcolor=COLORES["boton"], color=ft.colors.WHITE)
        retroceder_button = ft.ElevatedButton("Retroceder", icon=ft.icons.ARROW_BACK, bgcolor=COLORES["boton"], color=ft.colors.WHITE)

        problemas_container = ft.Container(
            content=ft.Column(
                [
                    ejercicio_text,
                    respuesta_container,
                    #ft.Row([retroceder_button, siguiente_button], spacing=20),
                    ft.Row([siguiente_button], alignment=ft.MainAxisAlignment.CENTER),
                    feedback_text,
                    status_row
                ], 
                spacing=20, expand=True
            ),
            padding=20,
            bgcolor=COLORES["accento"],
            border_radius=10,
            expand=True,
        )

        # Layout
        temporizador_text = ft.Text("20:00", size=32, color=COLORES["primario"], weight="bold", text_align=ft.TextAlign.CENTER)
        main_row = ft.Row([chat_box, problemas_container], spacing=20, expand=True)
        page.clean(); page.add(ft.Column([codigo_texto_visible, temporizador_text, main_row], spacing=20, expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER))

        # ---- Lógica de problemas ----
        def _submit_from_enter(e):
            val = (e.control.value or "").strip() if e and e.control else ""
            if val:
                enviar_respuesta(None)
            else:
                feedback_text.value = "Escribe una respuesta antes de enviar."; feedback_text.color = COLORES["error"]; page.update()

        def cargar_problema(id_problema: int):
            nonlocal problema_actual_id
            problema_actual_id = id_problema
            chat_area.controls.clear()
            try:
                r = requests.get(f"{BACKEND_URL_OBTENER_PROBLEMA}/{id_problema}")
                if r.status_code == 200:
                    p = r.json()
                    ejercicio_text.value = f"Problema {p.get('id', id_problema)}\n\n{p.get('enunciado', '')}"
                    ejercicio_text.text_align = ft.TextAlign.CENTER  # center title and statement
                    page.update()
                    respuesta_container.controls.clear()
                    tf = ft.TextField(
                        hint_text="Escribe tu respuesta (texto libre)…",
                        expand=True, multiline=True, min_lines=1, max_lines=6,
                        bgcolor=COLORES["secundario"], border_color=COLORES["secundario"], focused_border_color=COLORES["primario"], border_radius=15,
                        hint_style=ft.TextStyle(color=ft.colors.WHITE), on_submit=_submit_from_enter,
                    )
                    respuesta_container.controls.append(tf)
                    feedback_text.value = ""; status_row.visible = False
                    siguiente_button.disabled = False
                    retroceder_button.disabled = True  # back disabled for linear flow
                    user_input.disabled = False; send_button.disabled = False

                    def _focus():
                        tf.focus(); tf.selection = ft.TextSelection(0, len(tf.value or ""))
                        page.scroll_to(offset=99999, duration=200); page.update()
                    threading.Timer(0.05, _focus).start()
                else:
                    feedback_text.value = "Error al cargar el problema."; feedback_text.color = COLORES["error"]
            except Exception:
                feedback_text.value = "Error de conexión."; feedback_text.color = COLORES["error"]
            page.update()

        def enviar_respuesta(e):
            nonlocal problema_actual_id, stop_timer
            siguiente_button.disabled = True; send_button.disabled = True; page.update()
            val = ""
            if respuesta_container.controls and isinstance(respuesta_container.controls[0], ft.TextField):
                val = (respuesta_container.controls[0].value or "").strip()
            if not val:
                feedback_text.value = "La respuesta no puede estar vacía."; feedback_text.color = COLORES["error"]
                siguiente_button.disabled = False; send_button.disabled = False; page.update(); return
            try:
                resp = requests.post(f"{BACKEND_URL_VERIFICAR}/{problema_actual_id}", json={"respuesta": val, "codigo_identificacion": codigo})
                resp.raise_for_status()
            except Exception:
                feedback_text.value = "Error al registrar en el servidor."; feedback_text.color = COLORES["error"]
                siguiente_button.disabled = False; send_button.disabled = False; page.update(); return

            respuestas_usuario[problema_actual_id - 1] = val
            feedback_text.value = ""; save_snack.open = True
            status_icon.visible = True; status_text.value = "Guardado"; status_row.visible = True; page.update()

            def _hide():
                status_row.visible = False; page.update()
            threading.Timer(1.2, _hide).start()

            for i in range(problema_actual_id, len(respuestas_usuario)):
                if respuestas_usuario[i] is None:
                    cargar_problema(i + 1); return

            stop_timer = True
            feedback_text.value = "¡Has completado todos los problemas!"; feedback_text.color = COLORES["primario"]
            siguiente_button.disabled = True; retroceder_button.disabled = True; user_input.disabled = True; send_button.disabled = True
            page.update(); threading.Timer(3, mostrar_pantalla_encuesta_final).start()

        siguiente_button.on_click = enviar_respuesta

        def retroceder(_):
            feedback_text.value = "La navegación hacia atrás está deshabilitada en este flujo."; feedback_text.color = "orange"; page.update()
        retroceder_button.on_click = retroceder

        # start
        cargar_problema(1)

        # Temporizador (20min)
        def iniciar_temporizador():
            nonlocal stop_timer
            def cuenta():
                t = 120 * 60
                while t > 0 and not stop_timer:
                    m, s = divmod(t, 60)
                    temporizador_text.value = f"{m:02}:{s:02}"; page.update(); time.sleep(1); t -= 1
                if not stop_timer:
                    temporizador_text.value = "¡Tiempo terminado!"; siguiente_button.disabled = True; retroceder_button.disabled = True; page.update(); threading.Timer(3, mostrar_pantalla_encuesta_final).start()
            threading.Thread(target=cuenta, daemon=True).start()
        iniciar_temporizador()

    # =============== PANTALLA 5: ENCUESTA FINAL ===============
    def mostrar_pantalla_encuesta_final():
        def copiar_codigo_final(e):
            page.set_clipboard(page.client_storage.get("codigo_identificacion"))
            page.snack_bar = ft.SnackBar(ft.Text("Código copiado al portapapeles"), open=True); page.update()

        instruccion = ft.Text(
            "Después de terminar los problemas, te agradecería mucho que respondieras el siguiente cuestionario, ya que es muy importante conocer tu experiencia con el sistema. Por favor, copia y pega tu código de identificación en esta última encuesta. Al finalizarla, habrás completado tu participación en el estudio y podrás cerrar todas las pestañas utilizadas. Si leiste este mensaje con atencion, mandame un correo con el mensaje secreto 'quiero 10' y tendras 10 sobre 100 puntos extras en esta practica.",
            size=18, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.JUSTIFY,
        )
        codigo_btn = ft.TextButton(
            content=ft.Text(page.client_storage.get("codigo_identificacion"), size=26, weight="bold", color=COLORES["primario"], text_align=ft.TextAlign.CENTER),
            on_click=copiar_codigo_final,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(20, 10), side=ft.BorderSide(1.5, COLORES["boton"]), shape=ft.RoundedRectangleBorder(radius=8), bgcolor=ft.colors.WHITE),
        )
        link_final = ft.TextButton("Cuestionario Final", url="https://docs.google.com/forms/d/e/1FAIpQLScX0lriSeCq6YdRYQnOjHVV12x6IQX52eULPGObiaC5LGmi8g/viewform?usp=dialog", style=ft.ButtonStyle(color=ft.colors.BLACK, bgcolor="#2af721", padding=ft.padding.symmetric(20, 10), shape=ft.RoundedRectangleBorder(radius=8)))

        layout = ft.Column([instruccion, ft.Divider(10), codigo_btn, ft.Divider(20), link_final, ft.Divider(30)], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15)
        container = ft.Container(content=layout, padding=30, bgcolor=COLORES["accento"], border_radius=10, shadow=ft.BoxShadow(blur_radius=10, color=ft.colors.GREY_400), width=600)
        page.clean(); page.add(container)

    # Boot
    mostrar_pantalla_consentimiento()


if __name__ == "__main__":
    import os
    os.environ["FLET_FORCE_WEB"] = "1"  # 👈 forces web mode instead of desktop
    port = int(os.getenv("PORT", "3000"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=port)
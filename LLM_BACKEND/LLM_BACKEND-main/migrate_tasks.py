import os
import json
import warnings
import gevent.monkey
gevent.monkey.patch_all()

from app import app, db, Practica, Problema, ListaEjercicios, GrupoTarea, RespuestaUsuario, ChatLog
warnings.simplefilter("ignore")

def ejecutar_migracion():
    with app.app_context():
        print("🚀 Iniciando la migración de archivos .json a la estructura relacional...")
        
        # Localizar la carpeta de ejercicios
        base_dir = os.path.dirname(os.path.abspath(__file__))
        exercises_dir = os.path.join(base_dir, "exercises")
        
        if not os.path.exists(exercises_dir):
            print(f"❌ No se encontró la carpeta 'exercises' en la ruta: {exercises_dir}")
            return
            
        archivos_json = [f for f in os.listdir(exercises_dir) if f.endswith(".json")]
        print(f"📂 Se detectaron {len(archivos_json)} tareas físicas listas para procesar.")
        
        for filename in archivos_json:
            file_path = os.path.join(exercises_dir, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                titulo = data.get("title", filename)
                descripcion = data.get("description", "Sin descripción disponible.")
                
                # Convertir tiempo: si venía en segundos (ej. 3600), pasamos a minutos (60)
                tiempo_original = data.get("max_time", 60)
                max_time = tiempo_original // 60 if tiempo_original > 120 else tiempo_original
                
                # Evitar duplicados si el script se ejecuta más de una vez
                practica_existente = Practica.query.filter_by(titulo=titulo).first()
                if practica_existente:
                    print(f"⚠️ La práctica '{titulo}' ya existe en la BD. Saltando inserción base...")
                    practica_id = practica_existente.id
                else:
                    # Inserción de la nueva Práctica (quedan como globales del sistema por ahora)
                    nueva_practica = Practica(
                        profesor_id=None,
                        titulo=titulo,
                        descripcion=descripcion,
                        max_time=max_time,
                        rubricas=[]  # Estructura limpia para rúbricas relacionales futuras
                    )
                    db.session.add(nueva_practica)
                    db.session.flush()  # Generar ID de forma transaccional
                    practica_id = nueva_practica.id
                    
                    # Inserción de sus problemas asociados
                    problemas = data.get("problemas", [])
                    for idx, p in enumerate(problemas):
                        raw_id = str(p.get("id", idx + 1))
                        try:
                            # Extraer solo la parte entera del ID del ejercicio (ej: '1.1' -> 1)
                            numero_ejercicio = int(float(raw_id).split('.')[0])
                        except Exception:
                            numero_ejercicio = idx + 1
                            
                        nuevo_problema = Problema(
                            practica_id=practica_id,
                            numero_ejercicio=numero_ejercicio,
                            enunciado=p.get("enunciado", "Sin enunciado.")
                        )
                        db.session.add(nuevo_problema)
                    
                    print(f"✅ Práctica '{titulo}' integrada con éxito (ID: {practica_id}) con {len(problemas)} ejercicios.")
                
                # --- VINCULACIÓN RELACIONAL RECONSTRUCTIVA ---
                # 1. Enlazar en el catálogo activo de profesores
                vinc_cat = ListaEjercicios.query.filter_by(exercise_filename=filename).update({ListaEjercicios.practica_id: practica_id})
                
                # 2. Enlazar en las asignaciones de clases/grupos
                vinc_gpo = GrupoTarea.query.filter_by(exercise_filename=filename).update({GrupoTarea.practica_id: practica_id})
                
                # 3. Re-amarrar respuestas históricas de alumnos por nombre o archivo
                vinc_resp = RespuestaUsuario.query.filter(
                    (RespuestaUsuario.practice_name == filename) | (RespuestaUsuario.practice_name == titulo)
                ).update({RespuestaUsuario.practica_id: practica_id}, synchronize_session=False)
                
                # 4. Re-amarrar chats históricos de alumnos por nombre o archivo
                vinc_chat = ChatLog.query.filter(
                    (ChatLog.practice_name == filename) | (ChatLog.practice_name == titulo)
                ).update({ChatLog.practica_id: practica_id}, synchronize_session=False)
                
                if vinc_cat or vinc_gpo or vinc_resp or vinc_chat:
                    print(f"   🔗 Relaciones actualizadas: {vinc_cat} catálogo | {vinc_gpo} grupos | {vinc_resp} respuestas | {vinc_chat} chats.")
            
            except Exception as e:
                print(f"❌ Error crítico procesando {filename}: {str(e)}")
                db.session.rollback()
                continue
        
        db.session.commit()
        print("🎉 ¡Proceso de migración finalizado con éxito! Todos los datos huérfanos han sido enlazados.")

if __name__ == "__main__":
    ejecutar_migracion()
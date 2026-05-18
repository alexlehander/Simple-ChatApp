import gevent.monkey
gevent.monkey.patch_all()
from app import app, db
from sqlalchemy import text

def actualizar_esquema():
    with app.app_context():
        tablas_a_modificar = [
            "railway_lista_ejercicios",
            "railway_grupo_tarea",
            "railway_respuesta_usuario",
            "railway_chat_log",
            "railway_reporte_desempeno"
        ]
        
        print("🛠️  Iniciando actualización forzada del esquema...")
        for tabla in tablas_a_modificar:
            try:
                # Ejecutamos el comando SQL directo para agregar la columna
                db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN practica_id INT NULL;"))
                print(f"✅ Columna 'practica_id' agregada exitosamente a la tabla: {tabla}")
            except Exception as e:
                # Si falla, probablemente la columna ya exista o la tabla no esté creada
                print(f"⚠️ Aviso en {tabla} (probablemente la columna ya existía): {str(e).split(')')[0]})")
        
        db.session.commit()
        print("🎉 Proceso de alteración de tablas finalizado.")

if __name__ == "__main__":
    actualizar_esquema()
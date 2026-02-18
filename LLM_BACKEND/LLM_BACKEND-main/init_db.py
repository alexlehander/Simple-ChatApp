import gevent.monkey
gevent.monkey.patch_all()

import warnings
from app import app, db
from sqlalchemy import text

warnings.simplefilter("ignore")

def init_database():
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Tables created successfully!")
        
    # --- SCRIPT DE ACTUALIZACIÓN (MIGRACIÓN) ---
        print("Aplicando parche a las columnas de 'railway_analisis_interaccion'...")
        try:
            # Ampliamos las 3 columnas que modificaste a VARCHAR(50)
            db.session.execute(text("ALTER TABLE railway_analisis_interaccion MODIFY intent VARCHAR(50);"))
            db.session.execute(text("ALTER TABLE railway_analisis_interaccion MODIFY dimension VARCHAR(50);"))
            db.session.execute(text("ALTER TABLE railway_analisis_interaccion MODIFY color_asignado VARCHAR(50);"))
            db.session.commit()
            print("✅ Columnas 'intent', 'dimension' y 'color_asignado' ampliadas a 50 caracteres exitosamente.")
        except Exception as e:
            # Hacemos rollback por si falla (ej. si la tabla no existe o la BD no soporta el comando)
            db.session.rollback()
            print(f"⚠️ Nota al alterar la tabla: {e}")

if __name__ == "__main__":
    init_database()
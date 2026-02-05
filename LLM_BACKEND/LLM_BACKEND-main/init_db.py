from app import app, db

def init_database():
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Tables created successfully!")

if __name__ == "__main__":
    init_database()
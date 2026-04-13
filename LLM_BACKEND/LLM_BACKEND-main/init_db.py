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
        
if __name__ == "__main__":
    init_database()
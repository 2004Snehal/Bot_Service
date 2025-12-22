from server.app.db.database import engine, Base
from server.app.db.models import Bot, Schedule, Meeting

def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Database initialized.")

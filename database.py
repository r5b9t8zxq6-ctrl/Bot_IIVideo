from sqlalchemy import create_engine, Column, Integer, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config import DATABASE_URL

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    telegram_id = Column(Integer, primary_key=True)
    free_generations = Column(Integer, default=3)
    is_premium = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=True)

def init_db():
    Base.metadata.create_all(engine)

def get_user(tg_id: int):
    session = Session()
    user = session.get(User, tg_id)
    session.close()
    return user

def add_user(tg_id: int):
    session = Session()
    if not session.get(User, tg_id):
        session.add(User(telegram_id=tg_id))
        session.commit()
    session.close()

def decrement_free(tg_id: int):
    session = Session()
    user = session.get(User, tg_id)
    if user and user.free_generations > 0:
        user.free_generations -= 1
        session.commit()
    session.close()

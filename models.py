from sqlalchemy import Column, Integer, String, Boolean, ForeignKey   # ForeignKey is new
from database import Base


class User(Base):                                       # NEW: the users table
    __tablename__ = "users"                             # real table name in Postgres

    id = Column(Integer, primary_key=True, index=True)  # unique id, Postgres auto-creates it
    email = Column(String, unique=True, nullable=False) # unique = no two accounts can share an email
    hashed_password = Column(String, nullable=False)    # the scrambled password, never the real one


class NoteDB(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(String, default="")
    done = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)   # NEW: points at the note's owner
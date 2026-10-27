import os                                              # lets us read environment variables
from dotenv import load_dotenv                         # reads the .env file
from sqlalchemy import create_engine                   # makes the connection to Postgres
from sqlalchemy.orm import sessionmaker, declarative_base  # session maker + table parent class

load_dotenv()                                          # loads .env so DATABASE_URL becomes available

engine = create_engine(os.getenv("DATABASE_URL"))      # the actual connection to Postgres, built from your URL
SessionLocal = sessionmaker(bind=engine, autoflush=False)  # machine that makes sessions; changes only sent on commit
Base = declarative_base()                              # parent class every table model inherits from

def get_db():                                          # dependency that gives each route a session
    db = SessionLocal()                                # open a new session
    try:                                               # protected block
        yield db                                       # lend the session to the route, pause until it finishes
    finally:                                           # always runs, even if the route crashed
        db.close()                                     # close the session, free the connection
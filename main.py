import os                                                    # lets us read environment variables
from fastapi.responses import FileResponse               # lets a route return a file
from dotenv import load_dotenv                               # reads the .env file
from fastapi import FastAPI, HTTPException, Depends          # app object, error responses, "run this first" helper
from fastapi.security import OAuth2PasswordRequestForm       # reads the login form (username + password)
from pydantic import BaseModel                               # defines and validates the shape of incoming data
from sqlalchemy.orm import Session                           # type hint only: tells you `db` is a DB session
from google import genai                                     # new SDK (google-genai)
from google.genai import types                               # data shapes Gemini expects (Content, Part, Tool...)
from database import engine, Base, get_db, SessionLocal     # connection, table register, route session helper, tool session factory
from models import NoteDB, User                              # the table classes (also registers them for create_all)
from auth import hash_password, verify_password, create_access_token, get_current_user   # CHANGED: added get_current_user (the "who is this?" check)

load_dotenv()                                                # loads .env so os.getenv works below

API_KEY = os.getenv("GEMINI_API_KEY")                        # read the Gemini key from .env
if not API_KEY:                         # fail early with a clear message instead of a vague 403 later
    raise RuntimeError("GEMINI_API_KEY not found. Check your .env file.")

client = genai.Client(api_key=API_KEY)  # one client replaces genai.configure() + GenerativeModel()
MODEL = "gemini-2.5-flash"              # one place to change the model name
MAX_ROUNDS = 5                          # safety cap for the tool-calling loop

app = FastAPI()     #creating a fastapi object to use
Base.metadata.create_all(bind=engine)   # creates the users + notes tables in Postgres if missing


class Note(BaseModel):         #creating a note clss which will restrict rules on new entry
    title: str          #new title is always a string
    content: str = ""   # NEW: optional detailed content for the note, default empty string
    done: bool = False  #optional

class ChatRequest(BaseModel):  # NEW: shape of the body for POST /notes/chat
    message: str                # the user's natural-language request, e.g. "mark groceries as done"

class UserCreate(BaseModel):   # shape of the body for POST /signup
    email: str                  # required, text
    password: str               # required, text (the real password, only used to make the hash)


def note_to_dict(n: NoteDB) -> dict:                                                    # takes one DB row
    # DB rows are objects, not dicts. Gemini needs plain data, so convert one row to a dict.
    return {"id": n.id, "title": n.title, "content": n.content, "done": n.done}         # pick the fields we want to send out


# ============ TOOLS (the secretary: real functions the model can ask for) ============
# Named tool_... so they don't clash with your endpoint functions (get_all_notes etc.)
# Tools can't use Depends, so each opens its own session and closes it in `finally` (same idea as get_db).
# CHANGED: every tool now receives user_id FIRST. It comes from the login token, NOT from the model,
# so the model can never read or edit another user's notes.

def tool_get_notes(user_id: int):                                # CHANGED: needs to know whose notes to fetch
    db = SessionLocal()                                          # open a session just for this tool call
    try:                                                         # protected block: cleanup must always happen
        rows = db.query(NoteDB).filter(NoteDB.user_id == user_id).all()   # CHANGED: only THIS user's notes
        return {"notes": [note_to_dict(r) for r in rows]}        # rows -> dicts so Gemini can read them
    finally:                                                     # runs even if something above crashed
        db.close()                                               # always close, even on error

def tool_mark_note_done(user_id: int, note_id: int):             # CHANGED: user_id comes first, note_id comes from the model
    db = SessionLocal()                                           # open a session for this tool call
    try:                                                          # protected block
        row = db.query(NoteDB).filter(NoteDB.id == note_id, NoteDB.user_id == user_id).first()   # CHANGED: note must ALSO belong to this user
        if row is None:                                               # no match (or not theirs): return error as data for the model
            return {"status": "error", "message": "note not found"}   # the model reads this and reacts
        row.done = True                                               # change the real data
        db.commit()                                                   # save it to Postgres
        db.refresh(row)                                               # reload row from DB
        return {"status": "ok", "note": note_to_dict(row)}            # updated note so the model can describe it
    finally:                                                          # always runs
        db.close()                                                    # free the connection

# Lookup table: the name in the DECLARATION (what Gemini says) -> the real function above
registry = {"get_notes": tool_get_notes, "mark_note_done": tool_mark_note_done}

# ============ DECLARATIONS (the menu: descriptions for the model) ============
# user_id is deliberately NOT in these: the model doesn't know about it and can't choose it.
get_notes_decl = {
    "name": "get_notes",                              # must match the registry key exactly
    "description": "Fetch all the user's notes with id, title, content and done status.",
    "parameters": {"type": "object", "properties": {}},  # this tool takes no arguments
}

mark_done_decl = {
    "name": "mark_note_done",                         # must match the registry key exactly
    "description": (
        "Mark one note as done. Needs the note's numeric id. "
        "If the user only gives a title, ALWAYS call get_notes first to find the id yourself. "
        "Never ask the user for an id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "note_id": {"type": "integer", "description": "The note's id"}
        },
        "required": ["note_id"],                      # model must always provide this
    },
}

# Settings sent with every chat request (Gemini remembers nothing between calls)
chat_config = types.GenerateContentConfig(
    system_instruction=(
        "You are a helpful notes assistant. Users refer to notes by title, "
        "never by id. Use your tools to look things up instead of asking the user."
    ),
    temperature=0.2,                                  # low randomness = consistent tool choices
    tools=[types.Tool(function_declarations=[get_notes_decl, mark_done_decl])],
)


# ============ THE LOOP ============
def run_chat(user_msg: str, user_id: int) -> str:     # CHANGED: needs to know whose notes the tools may touch
    # History starts with just the user's message; it lives only for this one request
    contents = [types.Content(role="user", parts=[types.Part(text=user_msg)])]

    for _ in range(MAX_ROUNDS):                       # safety cap: no infinite loops
        # Send full history + menu to Gemini
        response = client.models.generate_content(
            model=MODEL, contents=contents, config=chat_config
        )
        model_content = response.candidates[0].content

        # Collect every tool request in the reply (there can be several at once)
        calls = [p.function_call for p in (model_content.parts or []) if p.function_call]

        # No tool requested = final text answer, so we're done
        if not calls:
            return response.text

        contents.append(model_content)                # save the model's request in history

        result_parts = []
        for fc in calls:
            args = dict(fc.args or {})                # args can be None for no-argument tools
            print(f"model wants: {fc.name}({args})")  # debug: see the model's request in the terminal

            if fc.name not in registry:               # tool not on the menu: refuse, tell the model
                result = {"status": "error", "message": f"unknown tool: {fc.name}"}
            else:
                try:
                    result = registry[fc.name](user_id, **args)   # CHANGED: WE pass user_id (from the token), the model only supplies the rest
                except Exception as e:                  # a crashing tool becomes data, not a dead request
                    result = {"status": "error", "message": str(e)}

            result_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": result})
            )

        # Results go back as role "user" (information coming to the model from outside)
        contents.append(types.Content(role="user", parts=result_parts))

    return "Stopped: too many tool calls."            # only reached if every round used a tool


#we always write function just after tht particular app.get line or u can say an endpoint
#and use docs to perform every action bcs it needs a frontend
# status codes:
# if in 200 line - everything is ok
# if in 400 line - something wrong with information provided
# if in 500 line - something is wrong with server

@app.get("/", include_in_schema=False)     # the page people land on; include_in_schema=False hides it from /docs
def home():
    return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))   # send index.html (it sits next to main.py)


# ============ AUTH ROUTES (public: no token needed) ============
@app.post("/signup", status_code=201)                 # create an account (201 = Created)
def signup(user: UserCreate, db: Session = Depends(get_db)):   # body checked by UserCreate, db session from get_db
    email = user.email.strip().lower()                # "A@x.com" and "a@x.com" should be the same account
    if db.query(User).filter(User.email == email).first():     # email already taken?
        raise HTTPException(status_code=400, detail="Email already registered")   # stop and send a 400 error
    row = User(email=email, hashed_password=hash_password(user.password))   # store the HASH, never the password
    db.add(row)                                       # stage the new user (draft in memory)
    db.commit()                                       # actually save to Postgres
    db.refresh(row)                                   # reload so row.id is filled in
    return {"id": row.id, "email": row.email}         # never send the hash back

@app.post("/login")                                   # exchange email + password for a token
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):   # reads the login form + db session
    email = form.username.strip().lower()             # the form field is always called "username", we put the email in it
    user = db.query(User).filter(User.email == email).first()   # find the user by email, None if no match
    if user is None or not verify_password(form.password, user.hashed_password):   # no such user OR wrong password
        raise HTTPException(status_code=401, detail="Wrong email or password")   # same message for both, so attackers can't tell which was wrong
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}   # the "wristband" the client sends later


# ============ NOTES ROUTES (protected: token required, each user sees only their own notes) ============
# Depends(get_current_user) = "check the token first". No token or a bad one = 401 before the route even runs.
# NoteDB.user_id == current_user.id = "only rows owned by the logged-in user".
@app.get("/notes/summarize")                          # specific route MUST come before /notes/{note_id}
def summarize_notes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):   # CHANGED: needs a logged-in user
    rows = db.query(NoteDB).filter(NoteDB.user_id == current_user.id).all()   # CHANGED: only this user's notes
    if not rows:                                      # this user has no notes
        return {"summary": "No notes to summarize"}   # nothing to send to Gemini

    # n['title'] -> n.title (rows are objects, not dicts)
    notes_text = "\n".join(                           # join one line per note into a single text block
        [f"- {n.title}: {n.content}" if n.content else f"- {n.title}" for n in rows]   # include content only if there is some
    )
    prompt = f"Summarize these notes:\n{notes_text}"  # the instruction + the notes text

    response = client.models.generate_content(        # ask Gemini for a summary
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction="You are a helpful assistant that summarizes notes concisely.",
            temperature=0.3,                          # low randomness = focused summary
            max_output_tokens=100                     # cap the length of the summary
        )
    )
    return {"summary": response.text}                 # send Gemini's text back

@app.post("/notes/chat")                              # talk to your notes in plain English
def chat_with_notes(req: ChatRequest, current_user: User = Depends(get_current_user)):   # CHANGED: needs a logged-in user
    try:                                              # protect against Gemini errors
        return {"reply": run_chat(req.message, current_user.id)}   # CHANGED: pass the user's id (from the token) to the loop
    except Exception as e:                            # Gemini down, quota hit, bad key... -> clean 502
        raise HTTPException(status_code=502, detail=f"AI service error: {e}")   # tell the client the AI side failed

@app.get("/notes")      #when user is trying to access notes
def get_all_notes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):    # just return all the notes (of this user)
    rows = db.query(NoteDB).filter(NoteDB.user_id == current_user.id).all()   # CHANGED: only this user's rows
    return [note_to_dict(r) for r in rows]            # rows -> dicts for JSON

@app.post("/notes", status_code=201)     #to create a new node (201 = Created)
def create_note(note: Note, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):   # body checked by Note + logged-in user
    row = NoteDB(title=note.title, content=note.content, done=note.done, user_id=current_user.id)   # CHANGED: stamp the owner from the token, never from the request body
    db.add(row)                                       # stage it (draft in memory)
    db.commit()                                       # actually save to Postgres
    db.refresh(row)                                   # reload so row.id is filled in
    return note_to_dict(row)                          # send the saved note back as a dict

@app.get("/notes/{note_id}")        #get a particular note
def get_note(note_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):   # note_id from the URL + logged-in user
    row = db.query(NoteDB).filter(NoteDB.id == note_id, NoteDB.user_id == current_user.id).first()   # CHANGED: the note must ALSO be yours
    if row is None:                                   # missing OR someone else's: both look the same, so 404 (not 403)
        raise HTTPException(status_code=404, detail="Note not found")       # mannually creating a exception if no such note exists
    return note_to_dict(row)                          # send the note as a dict

@app.put("/notes/{note_id}")        #updating notes
def update_note(note_id: int, updated_note: Note, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):   # id from URL, new values from body, logged-in user
    row = db.query(NoteDB).filter(NoteDB.id == note_id, NoteDB.user_id == current_user.id).first()   # CHANGED: find the note only if it's yours
    if row is None:                                   # missing or not yours
        raise HTTPException(status_code=404, detail="Note not found")   # stop and send a 404
    row.title = updated_note.title                    # change the fields on the row object
    row.content = updated_note.content                # new content
    row.done = updated_note.done                      # new done status
    db.commit()                                       # save changes to Postgres
    db.refresh(row)                                   # reload the saved version
    return note_to_dict(row)                          # send the updated note back

@app.delete("/notes/{note_id}")     #to delete node
def delete_note(note_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):   # id from the URL + logged-in user
    row = db.query(NoteDB).filter(NoteDB.id == note_id, NoteDB.user_id == current_user.id).first()   # CHANGED: find the note only if it's yours
    if row is None:                                   # missing or not yours
        raise HTTPException(status_code=404, detail="Note not found")   # stop and send a 404
    db.delete(row)                                    # stage the delete
    db.commit()                                       # actually remove it from Postgres
    return {"message": "Note deleted"}                # confirm to the client
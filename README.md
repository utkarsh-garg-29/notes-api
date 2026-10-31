# Notes API

An AI-powered notes app built with **FastAPI** and **PostgreSQL**. Users sign up, log in, manage their own private notes, and use **Gemini** to summarize notes or chat with them.

**Live demo:** https://notes-api-zeta-ruddy.vercel.app

## Features

- **Full CRUD** for notes (create, read, update, delete)
- **Authentication**: signup/login with bcrypt-hashed passwords and JWT tokens
- **Per-user data**: every note belongs to a user, and users only see their own notes
- **AI summarization**: `/notes/summarize` condenses all of a user's notes using Gemini
- **AI chat with tool calling**: `/notes/chat` lets you ask questions about your notes in natural language
- **Simple frontend**: a single `index.html` served by FastAPI (login/signup, notes list, summarize, chat box)

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI, Pydantic |
| Database | PostgreSQL (Neon in production), SQLAlchemy |
| Auth | bcrypt, PyJWT |
| AI | Google Gemini API |
| Frontend | HTML, CSS, vanilla JavaScript |
| Deployment | Vercel |

## API Endpoints

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/signup` | Create a new account | No |
| POST | `/login` | Log in and receive a JWT | No |
| GET | `/notes` | List your notes | Yes |
| POST | `/notes` | Create a note | Yes |
| GET | `/notes/summarize` | AI summary of your notes | Yes |
| POST | `/notes/chat` | Chat with your notes (tool calling) | Yes |
| GET | `/notes/{note_id}` | Get one note | Yes |
| PUT | `/notes/{note_id}` | Update a note | Yes |
| DELETE | `/notes/{note_id}` | Delete a note | Yes |

Protected endpoints expect the header `Authorization: Bearer <token>`.

## Run Locally

```bash
# 1. Clone
git clone https://github.com/utkarsh-garg-29/notes-api.git
cd notes-api

# 2. Create a virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# 3. Create a .env file (see below)

# 4. Start the server
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 in your browser.

### Environment variables

Create a `.env` file in the project root (never commit it):

```
GEMINI_API_KEY=your-gemini-key
DATABASE_URL=postgresql://user:password@localhost:5432/notes_db
SECRET_KEY=a-long-random-string
```

## Project Structure

```
notes-api/
├── main.py             # FastAPI app and routes
├── index.html          # Frontend
├── requirements.txt
├── .env                # Secrets (not committed)
└── .gitignore
```

## What I Learned

- Designing REST APIs with proper status codes, validation, and error handling
- Route ordering in FastAPI (specific paths before variable ones)
- Password hashing and JWT-based authentication
- Managing database sessions with SQLAlchemy
- Integrating an LLM API, including system prompts, temperature, and tool calling
- Keeping secrets out of source control with environment variables
- Deploying a FastAPI app on Vercel with a serverless Postgres database

## Author

**Utkarsh Garg**: [GitHub](https://github.com/utkarsh-garg-29)

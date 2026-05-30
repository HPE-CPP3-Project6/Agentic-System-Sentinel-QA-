# Smart Task Manager

A full-stack task management application built with **FastAPI** (backend) and **React + Vite** (frontend).

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy, SQLite |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Frontend | React 18, Vite, Tailwind CSS v4 |
| HTTP Client | Axios |
| Routing | React Router DOM v6 |

## Project Structure

```
smart-task-manager/
├── backend/               # FastAPI application
│   ├── main.py            # App entry point
│   ├── auth.py            # JWT + bcrypt helpers
│   ├── config.py          # Pydantic settings
│   ├── database.py        # SQLAlchemy engine & session
│   ├── models.py          # ORM models (User, Task, AuditLog)
│   ├── schemas.py         # Pydantic request/response schemas
│   ├── routers/
│   │   ├── auth_router.py # /register, /login, /logout
│   │   └── task_router.py # /tasks CRUD + pagination + filters
│   ├── purge_deleted_tasks.py
│   ├── requirements.txt
│   └── .env.example
└── frontend/              # Vite + React application
    ├── src/
    │   ├── api/
    │   │   ├── axios.js        # Axios instance + JWT interceptor
    │   │   └── tasks.js        # Task API service
    │   ├── context/
    │   │   └── AuthContext.jsx # Global auth state
    │   ├── components/
    │   │   ├── Login.jsx
    │   │   ├── Register.jsx
    │   │   ├── Dashboard.jsx   # Main task dashboard
    │   │   ├── TaskCard.jsx    # Single task display
    │   │   ├── TaskForm.jsx    # Create / edit form
    │   │   ├── FilterBar.jsx   # Search + filter + sort controls
    │   │   ├── Pagination.jsx  # Page navigation
    │   │   └── ProtectedRoute.jsx
    │   ├── App.jsx
    │   └── main.jsx
    └── package.json
```

## Getting Started

### Backend

```bash
# 1. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment variables
copy .env.example .env       # then edit .env with your SECRET_KEY

# 4. Start the server
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at: `http://localhost:5173`

## Features

- **Authentication** — Register, login, logout with JWT
- **Task CRUD** — Create, read, update, soft-delete tasks
- **Priority badges** — High (red), Medium (amber), Low (blue)
- **Status toggle** — Active ↔ Completed with visual strikethrough
- **Undo delete** — 5-second countdown toast to undo deletions
- **Filtering** — By priority, status, and date (Today / Upcoming / Overdue)
- **Sorting** — By due date, priority, or creation time
- **Search** — Client-side title search with 500ms debounce
- **Pagination** — Page navigation with smart ellipsis controls
- **Audit logging** — Immutable CREATE/DELETE event log

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```env
SECRET_KEY=your-long-random-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=30
SOFT_DELETE_UNDO_WINDOW_MINUTES=30
```

> ⚠️ Never commit your `.env` file. It is listed in `.gitignore`.

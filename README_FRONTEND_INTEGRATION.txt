AI Semantic Cache Gateway v2.0.0 - Final UI Integration

This package includes the backend app and the frontend at the exact location
expected by app/api/server.py:

  <project root>/frontend/

The backend file app/api/server.py uses:
  FRONTEND_DIR = BASE_DIR / "frontend"

The authentication UI uses the backend OAuth routes described below.

Authentication:
  GET  /api/auth/oauth/github/start
  GET  /api/auth/oauth/google/start
  GET  /api/auth/me
  POST /api/auth/logout

The frontend login page is:
  /pages/login.html

Start the backend using the existing app/run_server.py or your normal uvicorn
command, then open the gateway root URL. Unauthenticated users are redirected
to /pages/login.html.

The dashboard/playground use live backend APIs and do not hard-code the sample
numbers shown in the reference screenshots.

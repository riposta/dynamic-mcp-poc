"""FastAPI wrapper with Keycloak OIDC login protecting ADK Web UI"""
import sys
import os
import secrets
import hashlib
import base64
from pathlib import Path
from urllib.parse import urlencode

# When run as `python agent/web.py`, this module is loaded as __main__.
# ADK's agent loader later imports `agent.web` as a separate module.
# Register this module as `agent.web` so both share the same state.
sys.modules["agent.web"] = sys.modules[__name__]

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import URLSafeSerializer
from google.adk.cli.fast_api import get_fast_api_app

load_dotenv()

# Keycloak OIDC config
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "mcp-poc")
CLIENT_ID = os.getenv("KEYCLOAK_ADK_CLIENT_ID", "adk-web-client")
REDIRECT_URI = "http://localhost:8000/callback"
AUTH_ENDPOINT = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
TOKEN_ENDPOINT = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

# Session
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
serializer = URLSafeSerializer(SESSION_SECRET)
COOKIE_NAME = "mcp_session"

# In-memory token store: session_id -> access_token
sessions = {}
current_token = None  # global token for header_provider in main.py

# PKCE state: verifier stored between redirect and callback
_pkce_verifiers = {}

app = FastAPI()


def _generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _get_session_id(request: Request):
    """Extract session ID from cookie"""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        try:
            return serializer.loads(cookie)
        except Exception:
            return None
    return None


def _get_token(request: Request):
    """Get access token for the current session"""
    sid = _get_session_id(request)
    if sid:
        return sessions.get(sid)
    return None


LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head><title>MCP Gateway - Login</title>
<style>
  body { font-family: sans-serif; display: flex; justify-content: center; align-items: center;
         height: 100vh; margin: 0; background: #f5f5f5; }
  .card { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1);
          text-align: center; }
  a { display: inline-block; margin-top: 1rem; padding: .75rem 1.5rem; background: #1a73e8;
      color: white; text-decoration: none; border-radius: 4px; }
  a:hover { background: #1557b0; }
</style>
</head>
<body>
  <div class="card">
    <h2>MCP Gateway Agent</h2>
    <p>Sign in to access the AI agent with dynamic MCP tools.</p>
    <a href="/login">Login with Keycloak</a>
  </div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if _get_token(request):
        return RedirectResponse("/adk/dev-ui/")
    return HTMLResponse(LOGIN_PAGE)


@app.get("/login")
async def login():
    """Redirect to Keycloak authorization endpoint with PKCE"""
    state = secrets.token_urlsafe(32)
    verifier, challenge = _generate_pkce()
    _pkce_verifiers[state] = verifier

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTH_ENDPOINT}?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/callback")
async def callback(code: str = None, state: str = None, error: str = None, error_description: str = None):
    """Handle Keycloak callback - exchange auth code for tokens"""
    global current_token

    if error:
        return HTMLResponse(f"Keycloak error: {error} - {error_description or ''}", status_code=403)

    if not code or not state:
        return HTMLResponse("Missing code or state parameter", status_code=400)

    verifier = _pkce_verifiers.pop(state, None)
    if not verifier:
        return HTMLResponse("Invalid state", status_code=400)

    # Exchange authorization code for tokens
    async with httpx.AsyncClient() as http:
        resp = await http.post(TOKEN_ENDPOINT, data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        })
        resp.raise_for_status()
        tokens = resp.json()

    access_token = tokens["access_token"]

    # Store in session
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = access_token
    current_token = access_token

    # Set session cookie and redirect to ADK UI
    response = RedirectResponse("/adk/dev-ui/")
    signed = serializer.dumps(session_id)
    response.set_cookie(COOKIE_NAME, signed, httponly=True, samesite="lax")
    return response


@app.get("/debug/token")
async def debug_token(request: Request):
    """Check if current token is set (for debugging)"""
    token = _get_token(request)
    return {
        "session_token": token,
        "global_token": current_token,
    }


@app.get("/logout")
async def logout(request: Request):
    global current_token
    sid = _get_session_id(request)
    if sid:
        sessions.pop(sid, None)
    current_token = None
    response = RedirectResponse("/")
    response.delete_cookie(COOKIE_NAME)
    return response


# Mount ADK Web app under /adk
adk_app = get_fast_api_app(
    agents_dir=str(Path(__file__).parent.parent),
    allow_origins=["*"],
    web=True,
    url_prefix="/adk",
)
app.mount("/adk", adk_app)


if __name__ == "__main__":
    port = int(os.getenv("ADK_PORT", "8000"))
    print(f"Starting ADK Web with Keycloak auth on http://localhost:{port}")
    print(f"Keycloak: {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}")
    print(f"Login at http://localhost:{port}/")
    uvicorn.run(app, host="0.0.0.0", port=port)

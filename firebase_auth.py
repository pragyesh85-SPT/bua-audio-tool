"""Firebase Authentication for Streamlit via the Identity Toolkit REST API.

Only needs the Firebase Web API key (NOT a service account). Users are
managed in the Firebase console (Authentication -> Users). Sign-up from the
app is intentionally disabled so only users you create can log in.
"""

import os
import time

import requests
import streamlit as st

SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
REFRESH_URL = "https://securetoken.googleapis.com/v1/token"

# Refresh the ID token a minute before it actually expires.
_EXPIRY_MARGIN_SECONDS = 60


def get_api_key():
    """Firebase Web API key from env var or Streamlit secrets."""
    key = os.environ.get("FIREBASE_WEB_API_KEY")
    if key:
        return key
    try:
        return st.secrets["FIREBASE_WEB_API_KEY"]
    except Exception:
        return None


def _sign_in(api_key, email, password):
    resp = requests.post(
        SIGN_IN_URL,
        params={"key": api_key},
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code != 200:
        code = data.get("error", {}).get("message", "UNKNOWN_ERROR")
        friendly = {
            "INVALID_LOGIN_CREDENTIALS": "Wrong email or password.",
            "EMAIL_NOT_FOUND": "No account with that email.",
            "INVALID_PASSWORD": "Wrong password.",
            "USER_DISABLED": "This account has been disabled.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Try again later.",
        }.get(code, f"Login failed ({code}).")
        raise ValueError(friendly)
    return data


def _refresh(api_key, refresh_token):
    resp = requests.post(
        REFRESH_URL,
        params={"key": api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _store_session(email, id_token, refresh_token, expires_in):
    st.session_state["auth_user"] = {
        "email": email,
        "id_token": id_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + int(expires_in) - _EXPIRY_MARGIN_SECONDS,
    }


def logout():
    st.session_state.pop("auth_user", None)


def require_login():
    """Gate the app behind Firebase email/password login.

    Returns the logged-in user dict. If FIREBASE_WEB_API_KEY is not
    configured, auth is skipped (local development mode) and None is
    returned. Calls st.stop() while the user is not logged in.
    """
    api_key = get_api_key()
    if not api_key:
        st.sidebar.warning("Auth disabled: FIREBASE_WEB_API_KEY not set (local dev mode).")
        return None

    user = st.session_state.get("auth_user")

    # Refresh the token if it is about to expire; force re-login on failure.
    if user and time.time() >= user["expires_at"]:
        try:
            data = _refresh(api_key, user["refresh_token"])
            _store_session(user["email"], data["id_token"], data["refresh_token"], data["expires_in"])
            user = st.session_state["auth_user"]
        except Exception:
            logout()
            user = None

    if user:
        st.sidebar.markdown(f"Signed in as **{user['email']}**")
        if st.sidebar.button("Log out"):
            logout()
            st.rerun()
        return user

    st.title("🎵 Bua Audio Tool")
    st.subheader("Sign in")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        try:
            data = _sign_in(api_key, email.strip(), password)
            _store_session(data["email"], data["idToken"], data["refreshToken"], data["expiresIn"])
            st.rerun()
        except ValueError as e:
            st.error(str(e))
        except requests.RequestException:
            st.error("Could not reach the authentication server. Try again.")

    st.stop()

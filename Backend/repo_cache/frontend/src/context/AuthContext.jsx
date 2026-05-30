/**
 * src/context/AuthContext.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Global authentication state for the entire React app.
 *
 * State kept here:
 *   · token        – raw JWT string (persisted in localStorage)
 *   · user         – decoded payload *or* a simple `{ email }` object so
 *                    child components can greet the logged-in user.
 *   · isAuthenticated – boolean derived from `token` being non-null
 *
 * Functions exposed:
 *   · register(email, password)  → POST /register
 *   · login(email, password)     → POST /login  (OAuth2 form-data)
 *   · logout()                   → clears state + localStorage
 *
 * Why Context instead of a library (Redux, Zustand, etc.)?
 *   Auth state is read globally but mutated rarely. React Context + useState
 *   is the simplest correct solution at this scale.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { createContext, useContext, useState, useCallback } from 'react'
import api from '../api/axios'

// ── 1. Create the context with a sensible default shape ──────────────────────
const AuthContext = createContext({
  user: null,
  token: null,
  isAuthenticated: false,
  login: async () => {},
  register: async () => {},
  logout: () => {},
})

// ── 2. Provider component ─────────────────────────────────────────────────────
export function AuthProvider({ children }) {
  // Rehydrate from localStorage so a page refresh doesn't log the user out
  const [token, setToken] = useState(() => localStorage.getItem('access_token'))
  const [user, setUser]   = useState(() => {
    const saved = localStorage.getItem('auth_user')
    return saved ? JSON.parse(saved) : null
  })

  // Derived flag — single source of truth
  const isAuthenticated = Boolean(token)

  // ── Helper: persist token + user and update state ─────────────────────────
  const _persistSession = useCallback((newToken, newUser) => {
    localStorage.setItem('access_token', newToken)
    localStorage.setItem('auth_user',    JSON.stringify(newUser))
    setToken(newToken)
    setUser(newUser)
  }, [])

  // ── register ──────────────────────────────────────────────────────────────
  // Calls POST /register then immediately logs the user in so they don't need
  // to fill the login form again after signing up.
  const register = useCallback(async (email, password) => {
    // Step 1: create the account
    await api.post('/register', { email, password })

    // Step 2: auto-login to grab the token
    await _doLogin(email, password)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── login ─────────────────────────────────────────────────────────────────
  const login = useCallback(async (email, password) => {
    await _doLogin(email, password)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Internal: shared login logic (also used after registration)
  // FastAPI's OAuth2PasswordRequestForm expects application/x-www-form-urlencoded,
  // NOT JSON — we use URLSearchParams to encode it correctly.
  async function _doLogin(email, password) {
    const formData = new URLSearchParams()
    formData.append('username', email)   // FastAPI uses "username" for the email field
    formData.append('password', password)

    const { data } = await api.post('/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    // data = { access_token: "...", token_type: "bearer" }
    _persistSession(data.access_token, { email })
  }

  // ── logout ────────────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    try {
      // Inform the backend (stateless soft-logout — client just discards token)
      await api.post('/logout')
    } catch {
      /* ignore — we clear the local state regardless */
    } finally {
      localStorage.removeItem('access_token')
      localStorage.removeItem('auth_user')
      setToken(null)
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, isAuthenticated, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

// ── 3. Convenience hook ────────────────────────────────────────────────────────
// Usage: const { login, isAuthenticated } = useAuth()
export function useAuth() {
  return useContext(AuthContext)
}

/**
 * src/api/axios.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Configured Axios instance for the Smart Task Manager backend.
 *
 * Why a custom instance instead of the default `axios`?
 *   · Centralises the baseURL so we never repeat it across the app.
 *   · The request interceptor gives us one place to inject the JWT — any
 *     future change (e.g. switching from localStorage to a cookie) only
 *     requires editing this single file.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import axios from 'axios'

// ── 1. Base instance ──────────────────────────────────────────────────────────
const api = axios.create({
  baseURL: 'http://localhost:8000', // FastAPI dev server
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── 2. Request interceptor — attach JWT automatically ────────────────────────
//
// Runs *before* every request leaves the browser.
// We read the token from localStorage on each call (not once at startup) so
// that a freshly-issued token after login is picked up immediately without
// reloading the page or recreating the Axios instance.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')

    if (token) {
      // FastAPI's OAuth2PasswordBearer scheme expects "Bearer <token>"
      config.headers.Authorization = `Bearer ${token}`
    }

    return config   // must return the (possibly modified) config
  },
  (error) => Promise.reject(error)  // pass request-construction errors through
)

export default api

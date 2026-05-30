/**
 * src/App.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Application root — sets up React Router and wraps the tree in AuthProvider.
 *
 * Route map:
 *   /               → redirect to /login
 *   /login          → <Login />         (public)
 *   /register       → <Register />      (public)
 *   /dashboard      → <Dashboard />     (protected — requires valid JWT)
 *
 * ProtectedRoute redirects unauthenticated users to /login and restores the
 * originally requested path after a successful login.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute   from './components/ProtectedRoute'
import Login            from './components/Login'
import Register         from './components/Register'
import Dashboard        from './components/Dashboard'

export default function App() {
  return (
    // AuthProvider must wrap BrowserRouter so that auth-aware components
    // (like ProtectedRoute) can also use navigation hooks.
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/login"    element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Protected routes */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />

          {/* Catch-all — redirect unknown URLs to login */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

/**
 * src/components/ProtectedRoute.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Wrapper that checks authentication before rendering a protected page.
 *
 * Usage:
 *   <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
 *
 * Behaviour:
 *   · Authenticated   → render children as-is.
 *   · Unauthenticated → <Navigate to="/login" replace> so the browser history
 *     doesn't record the failed attempt (the back button won't replay it).
 *   · `state={{ from: location }}` lets the Login page redirect back to the
 *     originally requested URL after a successful login.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    // Redirect to /login, preserving the URL they tried to visit
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return children
}

/**
 * src/components/Register.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Registration form.
 *
 * Validation (client-side):
 *   · All fields are required.
 *   · Password must be ≥ 8 chars, contain an uppercase letter and a digit.
 *     (Mirrors the backend's UserCreate validator so the user gets instant
 *     feedback without a round-trip.)
 *   · Confirm-password match check.
 *
 * Server errors handled:
 *   · 409 → "An account with this email address already exists."
 *   · 422 → first FastAPI validation message.
 *
 * After successful registration the context auto-logs the user in and this
 * page redirects straight to /dashboard.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function extractError(err) {
  const data = err?.response?.data
  if (!data) return 'Unable to reach the server. Please try again.'
  if (Array.isArray(data.detail)) return data.detail[0]?.msg ?? 'Validation error.'
  if (typeof data.detail === 'string') return data.detail
  return 'An unexpected error occurred.'
}

// Mirrors the backend's password complexity rules (NFR8 / schemas.py)
function validatePassword(pw) {
  if (pw.length < 8)              return 'Password must be at least 8 characters.'
  if (!/[A-Z]/.test(pw))          return 'Password must contain at least one uppercase letter.'
  if (!/[0-9]/.test(pw))          return 'Password must contain at least one digit.'
  return null
}

export default function Register() {
  const { register } = useAuth()
  const navigate     = useNavigate()

  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [confirm,  setConfirm]  = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  // Live password-strength indicator
  const strength = password.length === 0 ? 0
    : password.length < 8        ? 1
    : validatePassword(password) ? 2
    : 3

  const strengthLabel = ['', 'Weak', 'Fair', 'Strong']
  const strengthColor = ['', 'bg-red-500', 'bg-amber-400', 'bg-emerald-500']

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    // ── Client-side validation ─────────────────────────────────────────────
    if (!email.trim()) { setError('Please enter your email address.'); return }

    const pwErr = validatePassword(password)
    if (pwErr) { setError(pwErr); return }

    if (password !== confirm) { setError('Passwords do not match.'); return }

    setLoading(true)
    try {
      await register(email.trim(), password)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(extractError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900 flex items-center justify-center px-4">

      {/* ── Card ─────────────────────────────────────────────────────────── */}
      <div className="w-full max-w-md">

        {/* Logo / heading */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-indigo-500/20 border border-indigo-500/30 mb-4 backdrop-blur-sm">
            <svg className="w-8 h-8 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7.5v3m0 0v3m0-3h3m-3 0h-3m-2.25-4.125a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0ZM4 19.235v-.11a6.375 6.375 0 0 1 12.75 0v.109A12.318 12.318 0 0 1 10.374 21c-2.331 0-4.512-.645-6.374-1.766Z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Create your account</h1>
          <p className="text-slate-400 mt-1 text-sm">Start managing tasks smarter, today</p>
        </div>

        {/* Form card */}
        <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8 shadow-2xl">

          {/* Error banner */}
          {error && (
            <div className="mb-5 flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
              <svg className="w-4 h-4 text-red-400 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              <p className="text-red-300 text-sm">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-5">

            {/* Email */}
            <div>
              <label htmlFor="reg-email" className="block text-sm font-medium text-slate-300 mb-1.5">
                Email address
              </label>
              <input
                id="reg-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm
                           focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/50
                           transition-all duration-200"
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="reg-password" className="block text-sm font-medium text-slate-300 mb-1.5">
                Password
              </label>
              <input
                id="reg-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 chars, 1 uppercase, 1 digit"
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm
                           focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/50
                           transition-all duration-200"
              />

              {/* Strength indicator */}
              {password.length > 0 && (
                <div className="mt-2">
                  <div className="flex gap-1 h-1">
                    {[1, 2, 3].map((level) => (
                      <div
                        key={level}
                        className={`flex-1 rounded-full transition-all duration-300 ${
                          strength >= level ? strengthColor[strength] : 'bg-white/10'
                        }`}
                      />
                    ))}
                  </div>
                  <p className={`text-xs mt-1 font-medium transition-colors ${
                    strength === 1 ? 'text-red-400' : strength === 2 ? 'text-amber-400' : 'text-emerald-400'
                  }`}>
                    {strengthLabel[strength]}
                  </p>
                </div>
              )}
            </div>

            {/* Confirm password */}
            <div>
              <label htmlFor="reg-confirm" className="block text-sm font-medium text-slate-300 mb-1.5">
                Confirm password
              </label>
              <input
                id="reg-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Re-enter your password"
                className={`w-full bg-white/5 border rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm
                            focus:outline-none focus:ring-2 focus:ring-indigo-500/60
                            transition-all duration-200 ${
                              confirm.length > 0 && confirm !== password
                                ? 'border-red-500/50'
                                : 'border-white/10 focus:border-indigo-500/50'
                            }`}
              />
              {confirm.length > 0 && confirm !== password && (
                <p className="mt-1 text-xs text-red-400">Passwords don&apos;t match</p>
              )}
            </div>

            {/* Submit */}
            <button
              id="register-submit"
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed
                         text-white font-semibold rounded-xl px-4 py-2.5 text-sm
                         transition-all duration-200 active:scale-[0.98]
                         focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-transparent
                         flex items-center justify-center gap-2 mt-2"
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                  </svg>
                  Creating account…
                </>
              ) : 'Create account'}
            </button>
          </form>

          {/* Footer link */}
          <p className="mt-6 text-center text-sm text-slate-500">
            Already have an account?{' '}
            <Link to="/login" className="text-indigo-400 hover:text-indigo-300 font-medium transition-colors">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

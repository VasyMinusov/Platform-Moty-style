import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../api/client'
import './Auth.css'

export default function LoginPage() {
  const { login, verifyMfa } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // ── Шаг 1: email + password ──────────────────────────────────
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  // ── Шаг 2: MFA (если сервер вернул mfa_required) ─────────────
  const [mfaToken, setMfaToken] = useState(null)
  const [mfaCode, setMfaCode] = useState('')

  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const redirectTo = location.state?.from?.pathname || '/challenges'

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = await login(email.trim(), password)
      if (result.mfa_required) {
        setMfaToken(result.mfa_token)
        setMfaCode('')
        return
      }
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось войти')
    } finally {
      setLoading(false)
    }
  }

  async function handleMfaSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await verifyMfa(mfaToken, mfaCode.trim())
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Неверный код')
    } finally {
      setLoading(false)
    }
  }

  function handleCancelMfa() {
    setMfaToken(null)
    setMfaCode('')
    setError(null)
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <span className="auth-stamp">access request</span>
        <div className="auth-brand">
          <svg width="28" height="28" viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="32" cy="32" r="21" fill="none" stroke="var(--accent)" strokeWidth="4" />
            <path d="M32 15 L32 49 M15 32 L49 32" stroke="var(--accent)" strokeWidth="4" />
            <circle cx="32" cy="32" r="5" fill="var(--accent)" />
          </svg>
          <span className="brand-title" style={{ fontFamily: 'var(--font-display)', fontSize: 20 }}>
            ORDO
          </span>
        </div>

        {mfaToken === null ? (
          <>
            <h1 className="auth-title">Вход оператора</h1>
            <p className="auth-subtitle">
              Введите email и пароль. Если включён MFA — потребуется код из приложения.
            </p>

            {error && <div className="alert">{error}</div>}

            <form onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="password">Пароль</label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
                {loading ? 'Проверка…' : 'Войти'}
              </button>
            </form>

            <div className="auth-footer">
              Нет доступа? <Link to="/register">Подать заявку на регистрацию</Link>
            </div>
          </>
        ) : (
          <>
            <h1 className="auth-title">Второй фактор</h1>
            <p className="auth-subtitle">
              Введите 6-значный код из приложения-аутентификатора
              или backup-код (формат XXXXX-XXXXX).
            </p>

            {error && <div className="alert">{error}</div>}

            <form onSubmit={handleMfaSubmit}>
              <div className="field">
                <label htmlFor="mfa-code">Код</label>
                <input
                  id="mfa-code"
                  className="mono"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  placeholder="123456"
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
                {loading ? 'Проверка…' : 'Подтвердить'}
              </button>
              <button
                type="button"
                className="btn btn-block"
                style={{ marginTop: 10 }}
                onClick={handleCancelMfa}
                disabled={loading}
              >
                Отмена
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
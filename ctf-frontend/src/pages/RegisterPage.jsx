import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../api/client'
import './Auth.css'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await register(username, email, password)
      navigate('/challenges', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось зарегистрироваться')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <span className="auth-stamp">new file</span>
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
        <h1 className="auth-title">Открыть досье</h1>
        <p className="auth-subtitle">Регистрация нового оператора платформы.</p>

        {error && <div className="alert">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="username">Логин</label>
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
            />
          </div>
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
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? 'Создание…' : 'Зарегистрироваться'}
          </button>
        </form>

        <div className="auth-footer">
          Уже есть доступ? <Link to="/login">Войти</Link>
        </div>
      </div>
    </div>
  )
}



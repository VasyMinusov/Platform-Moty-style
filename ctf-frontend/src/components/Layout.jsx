import { NavLink, useNavigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { useAuth } from '../context/AuthContext'
import './Layout.css'

const NetworkBackground = lazy(() => import('./NetworkBackground'))

const NAV_ITEMS = [
  { to: '/challenges', label: 'Задания', code: '01' },
  { to: '/competitions', label: 'Соревнования', code: '02' },
  { to: '/profile', label: 'Досье', code: '03' },
  { to: '/writeups', label: 'Write‑ups', code: '04' },
  { to: '/lessons', label: 'Библиотека', code: '05' },
]

// Модератор и админ: просмотр пользователей
const STAFF_ITEMS = [
  { to: '/users', label: 'Пользователи', code: '06' },
  { to: '/admin/competitions', label: 'Соревнования', code: '07' },
]

const ADMIN_ITEMS = [
  { to: '/admin', label: 'Админ', code: '08' },
  { to: '/admin/writeups', label: 'Управление', code: '09' },
]

export default function Layout({ children }) {
  const { isAuthenticated, username, role, logout } = useAuth()
  const isAdmin = role === 'admin'
  const isModerator = role === 'moderator'
  const canViewUsers = isAdmin || isModerator
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <>
      <Suspense fallback={null}>
        <NetworkBackground />
      </Suspense>
      <div className="shell">
        <header className="shell-header">
          <div className="brand" onClick={() => navigate(isAuthenticated ? '/challenges' : '/login')}>
            <svg width="26" height="26" viewBox="0 0 64 64" aria-hidden="true">
              <circle cx="32" cy="32" r="21" fill="none" stroke="var(--accent)" strokeWidth="4" />
              <path d="M32 15 L32 49 M15 32 L49 32" stroke="var(--accent)" strokeWidth="4" />
              <circle cx="32" cy="32" r="5" fill="var(--accent)" />
            </svg>
            <div className="brand-text">
              <span className="brand-title">ORDO</span>
              <span className="brand-sub eyebrow">ctf training platform</span>
            </div>
          </div>

          {isAuthenticated && (
            <nav className="shell-nav">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
                >
                  <span className="nav-tab-code mono">{item.code}</span>
                  {item.label}
                </NavLink>
              ))}
              {canViewUsers && STAFF_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
                >
                  <span className="nav-tab-code mono">{item.code}</span>
                  {item.label}
                </NavLink>
              ))}
              {isAdmin && ADMIN_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
                >
                  <span className="nav-tab-code mono">{item.code}</span>
                  {item.label}
                </NavLink>
              ))}
            </nav>
          )}

          <div className="shell-actions">
            {isAuthenticated ? (
              <>
                <span className="mono operator-tag">
                  оператор: <strong>{username}</strong>
                  {isAdmin && <span style={{ color: 'var(--accent)', marginLeft: 6 }}>[admin]</span>}
                  {isModerator && <span style={{ color: 'var(--info)', marginLeft: 6 }}>[moderator]</span>}
                </span>
                <button className="btn" onClick={handleLogout}>
                  Выйти
                </button>
              </>
            ) : (
              <NavLink to="/login" className="btn btn-primary">
                Войти
              </NavLink>
            )}
          </div>
        </header>

        <main className="shell-main">{children}</main>
      </div>
    </>
  )
}



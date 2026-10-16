import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from 'react'
import { api, ApiError, setOnAuthLost, setTokenRefresher } from '../api/client'
import { decodeJwt } from '../api/jwt'

const AuthContext = createContext(null)

// За сколько секунд до истечения access-токена делать refresh.
//
// 60 секунд — компромисс:
//   - Больше 60 (например 5 минут) — refresh случается слишком часто,
//     бесполезная нагрузка на auth-service.
//   - Меньше 30 — риск, что между истечением и refresh пользователь
//     успеет сделать запрос и получит 401.
//
// 60 — стандарт из практики SPA (Auth0 SDK default).
const REFRESH_LEAD_TIME_SECONDS = 60


function _clearLocalStorage() {
  localStorage.removeItem('ctf_token')
  localStorage.removeItem('ctf_refresh_token')
  localStorage.removeItem('ctf_username')
  localStorage.removeItem('ctf_role')
}


export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('ctf_token'))
  const [refreshToken, setRefreshToken] = useState(
    () => localStorage.getItem('ctf_refresh_token'),
  )
  const [username, setUsername] = useState(() => localStorage.getItem('ctf_username'))
  const [role, setRole] = useState(() => localStorage.getItem('ctf_role'))

  // ── Singleton refresh ─────────────────────────────────────────────────
  //
  // Если 5 параллельных запросов одновременно получат 401, каждый
  // попробует refresh. Получится 5 POST /auth/refresh с одним и тем же
  // refresh-токеном. На стороне auth-service это replay detection
  // (использованный refresh помечается used=true после первой ротации),
  // и последующие 4 запроса убьют всю сессию.
  //
  // Решение: `refreshPromiseRef` хранит in-flight promise. Все
  // параллельные вызовы `refreshOnce()` ждут один и тот же результат.
  const refreshPromiseRef = useRef(null)

  // ── refreshOnce ───────────────────────────────────────────────────────
  //
  // Возвращает новый access_token или null (если refresh невозможен).
  // Не бросает исключений — все ошибки логируются, возвращается null.
  // Это упрощает использование в client.js: `if (newToken) retry()`.
  const refreshOnce = useCallback(async () => {
    // Уже идёт refresh — ждём его результат.
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current
    }

    const rt = localStorage.getItem('ctf_refresh_token')
    if (!rt) {
      return null
    }

    const promise = (async () => {
      try {
        const data = await api.refreshToken(rt)
        localStorage.setItem('ctf_token', data.access_token)
        localStorage.setItem('ctf_refresh_token', data.refresh_token)
        setToken(data.access_token)
        setRefreshToken(data.refresh_token)
        return data.access_token
      } catch (err) {
        // Refresh не сработал: токен отозван, истёк, или replay.
        // Возвращаем null — вызывающий код решает, что делать.
        //
        // НЕ логируем здесь с console.error: refresh с протухшим
        // токеном — нормальный сценарий (например, после F5 через
        // 8 дней). Логирование будет спамить консоль.
        return null
      } finally {
        refreshPromiseRef.current = null
      }
    })()

    refreshPromiseRef.current = promise
    return promise
  }, [])

  // ── logout ────────────────────────────────────────────────────────────
  //
  // Чистит localStorage + state + (опционально) отзывает refresh
  // на auth-service. Идемпотентна.
  const logout = useCallback(async ({ revokeRemote = false } = {}) => {
    const rt = localStorage.getItem('ctf_refresh_token')

    if (revokeRemote && rt) {
      // Best-effort: если auth-service недоступен, всё равно чистим
      // локально. Пользователь должен «разлогиниться» даже при
      // недоступности сервера.
      try {
        await api.logout(rt, false)
      } catch {
        /* ignore */
      }
    }

    _clearLocalStorage()
    setToken(null)
    setRefreshToken(null)
    setUsername(null)
    setRole(null)
  }, [])

  // ── Регистрация callback'ов в client.js ───────────────────────────────
  //
  // setOnAuthLost вызывается из apiFetch, когда 401 окончателен
  // (refresh не помог или его нет). AuthContext в этом случае:
  //   1. Чистит state.
  //   2. Редиректит на /login (если не уже там).
  //
  // setTokenRefresher даёт client.js доступ к refreshOnce — чтобы
  // не дублировать логику.
  useEffect(() => {
    setOnAuthLost(() => {
      logout()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
    })

    setTokenRefresher(refreshOnce)

    return () => {
      setOnAuthLost(null)
      setTokenRefresher(null)
    }
  }, [logout, refreshOnce])

  // ── Проактивный refresh по таймеру ────────────────────────────────────
  //
  // Смотрим exp access-токена, ставим setTimeout за REFRESH_LEAD_TIME_SECONDS
  // до истечения. Когда таймер сработает — обновляем токен в фоне.
  //
  // Если refresh не удался (например, refresh-токен тоже истёк) —
  // разлогиниваем. Пользователь увидит /login.
  //
  // Пересоздаём таймер при смене token — потому что новый access-token
  // имеет новый exp.
  useEffect(() => {
    if (!token) return

    const payload = decodeJwt(token)
    if (!payload?.exp) return

    const expiresAtMs = payload.exp * 1000
    const nowMs = Date.now()
    const refreshAtMs = expiresAtMs - REFRESH_LEAD_TIME_SECONDS * 1000
    const delayMs = Math.max(0, refreshAtMs - nowMs)

    const timer = setTimeout(async () => {
      const newToken = await refreshOnce()
      if (!newToken) {
        // Refresh не удался. Задача — не дать пользователю «зависнуть»
        // с протухшим токеном. Тихий logout → редирект на /login.
        await logout()
        if (!window.location.pathname.startsWith('/login')) {
          window.location.assign('/login')
        }
      }
    }, delayMs)

    return () => clearTimeout(timer)
  }, [token, refreshOnce, logout])

  // ── Подтягивание актуального профиля CTF ──────────────────────────────
  //
  // Запускается при смене токена. Источник: GET /api/auth/me
  // (ctf-backend). Первый запрос за нового пользователя триггерит
  // lazy provisioning на ctf-backend.
  //
  // Если 401 — client.js сам сделает refresh + retry (через
  // _tokenRefresher), а если не поможет — вызовет _onAuthLost.
  // Здесь нам НЕ нужно ловить 401 отдельно.
  useEffect(() => {
    if (!token) return

    let cancelled = false

    api
      .me()
      .then((data) => {
        if (cancelled) return
        setUsername(data.username)
        setRole(data.role)
        localStorage.setItem('ctf_username', data.username)
        localStorage.setItem('ctf_role', data.role)
      })
      .catch(() => {
        // Ошибка здесь уже означает, что client.js исчерпал все
        // попытки (refresh + retry) и вызвал _onAuthLost. Ничего
        // делать не надо — редирект уже произошёл.
      })

    return () => {
      cancelled = true
    }
  }, [token])

  // ── login ─────────────────────────────────────────────────────────────
  const login = useCallback(async (email, password) => {
    const data = await api.login(email, password)

    if (data.mfa_required) {
      return { mfa_required: true, mfa_token: data.mfa_token }
    }

    localStorage.setItem('ctf_token', data.access_token)
    localStorage.setItem('ctf_refresh_token', data.refresh_token)
    setToken(data.access_token)
    setRefreshToken(data.refresh_token)
    return { mfa_required: false }
  }, [])

  // ── verifyMfa ─────────────────────────────────────────────────────────
  const verifyMfa = useCallback(async (mfaToken, code) => {
    const data = await api.mfaVerify(mfaToken, code)
    localStorage.setItem('ctf_token', data.access_token)
    localStorage.setItem('ctf_refresh_token', data.refresh_token)
    setToken(data.access_token)
    setRefreshToken(data.refresh_token)
    return data
  }, [])

  // ── register ──────────────────────────────────────────────────────────
  const register = useCallback(async (uname, email, password) => {
    await api.register({ username: uname, email, password })
    return login(email, password)
  }, [login])

  const value = useMemo(
    () => ({
      token,
      refreshToken,
      username,
      role,
      isAuthenticated: Boolean(token),
      isAdmin: role === 'admin',
      isModerator: role === 'moderator',
      canManageLessons: role === 'admin' || role === 'moderator',
      canViewUsers: role === 'admin' || role === 'moderator',
      login,
      verifyMfa,
      register,
      logout,
    }),
    [token, refreshToken, username, role, login, verifyMfa, register, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}


export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth должен использоваться внутри <AuthProvider>')
  return ctx
}


export { ApiError }
import { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react'
import { decodeJwt, isTokenExpired } from '../api/jwt'
import { api, ApiError } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('ctf_token'))
  const [username, setUsername] = useState(() => localStorage.getItem('ctf_username'))
  const [role, setRole] = useState(() => localStorage.getItem('ctf_role'))

  useEffect(() => {
    if (token && isTokenExpired(token)) {
      logout()
    }
  }, [token])

  // При наличии токена — подтягиваем актуальные данные пользователя (роль, очки)
  useEffect(() => {
    if (!token) return
    api.me().then((data) => {
      setUsername(data.username)
      setRole(data.role)
      localStorage.setItem('ctf_username', data.username)
      localStorage.setItem('ctf_role', data.role)
    }).catch(() => {
      // токен протух или невалиден — сбрасываем
      logout()
    })
  }, [token])

  const login = useCallback(async (uname, password) => {
    const data = await api.login(uname, password)
    const payload = decodeJwt(data.access_token)
    const resolvedUsername = payload?.sub || uname
    localStorage.setItem('ctf_token', data.access_token)
    localStorage.setItem('ctf_username', resolvedUsername)
    setToken(data.access_token)
    setUsername(resolvedUsername)
    // роль подтянется useEffect'ом выше через /auth/me
  }, [])

  const register = useCallback(async (uname, email, password) => {
    await api.register({ username: uname, email, password })
    await login(uname, password)
  }, [login])

  const logout = useCallback(() => {
    localStorage.removeItem('ctf_token')
    localStorage.removeItem('ctf_username')
    localStorage.removeItem('ctf_role')
    setToken(null)
    setUsername(null)
    setRole(null)
  }, [])

  const value = useMemo(
    () => ({
      token,
      username,
      role,
      isAuthenticated: Boolean(token),
      isAdmin: role === 'admin',
      isModerator: role === 'moderator',
      // Модератор и админ ведут библиотеку занятий и видят список пользователей
      canManageLessons: role === 'admin' || role === 'moderator',
      canViewUsers: role === 'admin' || role === 'moderator',
      login,
      register,
      logout,
    }),
    [token, username, role, login, register, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth должен использоваться внутри <AuthProvider>')
  return ctx
}

export { ApiError }


import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ChallengesPage from './pages/ChallengesPage'
import ProfilePage from './pages/ProfilePage'
import AdminPage from './pages/AdminPage'
import WriteupsPage from './pages/WriteupsPage'
import NotFoundPage from './pages/NotFoundPage'
import { useAuth } from './context/AuthContext'
import WriteupsListPage from './pages/WriteupsListPage'
import WriteupDetailPage from './pages/WriteupDetailPage'
import UsersPage from './pages/UsersPage'
import LessonsListPage from './pages/LessonsListPage'
import LessonDetailPage from './pages/LessonDetailPage'
import LessonEditorPage from './pages/LessonEditorPage'

function AdminRoute({ children }) {
  const { isAuthenticated, isAdmin } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/challenges" replace />
  return children
}

// Модератор и админ: просмотр пользователей, ведение библиотеки занятий.
// Проверка идёт напрямую по role, а не через производные поля контекста —
// так гвард не ломается, если клиент обновился частично.
function StaffRoute({ children }) {
  const { isAuthenticated, role } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (role !== 'admin' && role !== 'moderator') return <Navigate to="/challenges" replace />
  return children
}

function LessonEditorRoute({ children }) {
  const { isAuthenticated, role } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (role !== 'admin' && role !== 'moderator') return <Navigate to="/lessons" replace />
  return children
}

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route
        path="/challenges"
        element={
          <RequireAuth>
            <Layout>
              <ChallengesPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/profile"
        element={
          <RequireAuth>
            <Layout>
              <ProfilePage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <Layout>
              <AdminPage />
            </Layout>
          </AdminRoute>
        }
      />
      <Route
        path="/admin/writeups"
        element={
          <AdminRoute>
            <Layout>
              <WriteupsPage />
            </Layout>
          </AdminRoute>
        }
      />
      <Route
        path="/writeups"
        element={
          <RequireAuth>
            <Layout>
              <WriteupsListPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/writeups/:slug"
        element={
          <RequireAuth>
            <Layout>
              <WriteupDetailPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <StaffRoute>
            <Layout>
              <UsersPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/lessons"
        element={
          <RequireAuth>
            <Layout>
              <LessonsListPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/lessons/new"
        element={
          <LessonEditorRoute>
            <Layout>
              <LessonEditorPage />
            </Layout>
          </LessonEditorRoute>
        }
      />
      <Route
        path="/lessons/:slug"
        element={
          <RequireAuth>
            <Layout>
              <LessonDetailPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/lessons/:slug/edit"
        element={
          <LessonEditorRoute>
            <Layout>
              <LessonEditorPage />
            </Layout>
          </LessonEditorRoute>
        }
      />
      <Route path="/" element={<Navigate to={isAuthenticated ? '/challenges' : '/login'} replace />} />
      <Route
        path="*"
        element={
          isAuthenticated ? (
            <Layout>
              <NotFoundPage />
            </Layout>
          ) : (
            <NotFoundPage />
          )
        }
      />
    </Routes>
  )
}


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

// Соревнования — публичные страницы
import CompetitionsListPage from './pages/CompetitionsListPage'
import CompetitionDetailPage from './pages/CompetitionDetailPage'
import CompetitionTeamPage from './pages/CompetitionTeamPage'

// Соревнования — админские страницы
import AdminCompetitionsListPage from './pages/admin/AdminCompetitionsListPage'
import AdminCompetitionEditorPage from './pages/admin/AdminCompetitionEditorPage'
import AdminCompetitionApplicationsPage from './pages/admin/AdminCompetitionApplicationsPage'
import AdminCompetitionChallengesPage from './pages/admin/AdminCompetitionChallengesPage'
import AdminCompetitionTeamsPage from './pages/admin/AdminCompetitionTeamsPage'
import AdminCompetitionDashboardPage from './pages/admin/AdminCompetitionDashboardPage'
import AdminCompetitionAppealsPage from './pages/admin/AdminCompetitionAppealsPage'

// ── Гварды ──────────────────────────────────────────────────────────

function AdminRoute({ children }) {
  const { isAuthenticated, isAdmin } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/challenges" replace />
  return children
}

// Модератор и админ: просмотр пользователей, ведение библиотеки занятий,
// управление соревнованиями. Проверка идёт напрямую по role, а не через
// производные поля контекста — так гвард не ломается, если клиент
// обновился частично.
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

// ── Приложение ──────────────────────────────────────────────────────

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      {/* Публичные auth-страницы */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Задания */}
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

      {/* Профиль */}
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

      {/* Соревнования — публичные */}
      <Route
        path="/competitions"
        element={
          <RequireAuth>
            <Layout>
              <CompetitionsListPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/competitions/:slug"
        element={
          <RequireAuth>
            <Layout>
              <CompetitionDetailPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/competitions/:slug/team"
        element={
          <RequireAuth>
            <Layout>
              <CompetitionTeamPage />
            </Layout>
          </RequireAuth>
        }
      />

      {/* Write-ups */}
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

      {/* Пользователи (модератор/админ) */}
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

      {/* Библиотека занятий */}
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

      {/* ── Админка (базовая) ── */}
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

      {/* ── Админка соревнований (модератор и админ) ── */}
      <Route
        path="/admin/competitions"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionsListPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/new"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionEditorPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/edit"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionEditorPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/applications"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionApplicationsPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/challenges"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionChallengesPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/teams"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionTeamsPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/dashboard"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionDashboardPage />
            </Layout>
          </StaffRoute>
        }
      />
      <Route
        path="/admin/competitions/:slug/appeals"
        element={
          <StaffRoute>
            <Layout>
              <AdminCompetitionAppealsPage />
            </Layout>
          </StaffRoute>
        }
      />

      {/* Корень и 404 */}
      <Route
        path="/"
        element={<Navigate to={isAuthenticated ? '/challenges' : '/login'} replace />}
      />
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
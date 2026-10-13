import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import './styles/tokens.css'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { NotificationsProvider } from './context/NotificationsContext.jsx'
import { ErrorBoundary } from './shared/ui/ErrorBoundary.jsx'
import { queryClient } from './shared/api/queryClient.js'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* ErrorBoundary стоит выше всего. Если упадёт даже роутер —
        пользователь увидит нормальную страницу, а не белый экран. */}
    <ErrorBoundary>
      {/* QueryClientProvider — провайдер кэша данных. Внутри него
          любая страница может использовать useQuery / useMutation. */}
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <NotificationsProvider>
              <App />
            </NotificationsProvider>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
)

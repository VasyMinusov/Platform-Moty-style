import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div style={{ textAlign: 'center', padding: '80px 20px' }}>
      <span className="eyebrow">ошибка 404</span>
      <h1 style={{ fontSize: 40, margin: '10px 0 14px' }}>Дело не найдено</h1>
      <p style={{ color: 'var(--text-dim)', marginBottom: 24 }}>
        Такой страницы не существует в архиве платформы.
      </p>
      <Link to="/challenges" className="btn btn-primary">
        Вернуться к заданиям
      </Link>
    </div>
  )
}



-- ═══════════════════════════════════════════════════════════════════════════
-- Init-скрипт PostgreSQL.
-- Выполняется ТОЛЬКО при первой инициализации volume.
-- ═══════════════════════════════════════════════════════════════════════════

-- UUID генерация (для будущих таблиц, если понадобится)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Криптографические функции (например, digest() для хеширования)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Триграммы для поиска (ILIKE с индексами)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Статистика по запросам (для мониторинга)
-- Раскомментировать в prod с pg_stat_statements.preload
-- CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Настройки для тестирования
-- По умолчанию: 100 соединений. Для тестов может не хватить.
ALTER SYSTEM SET max_connections = 200;

-- Логирование медленных запросов (>1s)
ALTER SYSTEM SET log_min_duration_statement = 1000;

-- Таймзона по умолчанию
ALTER DATABASE auth_db SET timezone TO 'UTC';

-- Проверка
SELECT 'PostgreSQL initialized successfully' AS status;
-- Добавление поля user_is_admin в таблицу users
-- Выполните этот скрипт в вашей базе данных PostgreSQL

-- Добавить поле user_is_admin
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_is_admin BOOLEAN DEFAULT FALSE;

-- Создать индекс для быстрого поиска админов
CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(user_is_admin) WHERE user_is_admin = TRUE;

-- Комментарий к полю
COMMENT ON COLUMN users.user_is_admin IS 'Флаг, указывающий, является ли пользователь администратором';

-- Пример: Назначить первого пользователя админом (замените user_id на реальный ID)
-- UPDATE users SET user_is_admin = TRUE WHERE user_id = 1;


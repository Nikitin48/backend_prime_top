-- Бэкап таблицы users
CREATE TABLE IF NOT EXISTS users_backup AS TABLE users;

-- Добавление столбцов (если их нет)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS user_name VARCHAR(50),
    ADD COLUMN IF NOT EXISTS user_surname VARCHAR(50);

-- Пример автозаполнения случайными именами/фамилиями
-- (простая выборка по массивам; при необходимости замените на свои списки)
WITH first AS (
    SELECT UNNEST(ARRAY['Александр','Мария','Иван','Екатерина','Дмитрий','Анна','Никита','Елена','Михаил','Ольга']) AS fn,
           generate_series(1,10) AS rn
),
last AS (
    SELECT UNNEST(ARRAY['Иванов','Петрова','Сидоров','Кузнецова','Смирнов','Попова','Волков','Соколова','Морозов','Лебедева']) AS ln,
           generate_series(1,10) AS rn
)
UPDATE users u
SET user_name = f.fn,
    user_surname = l.ln
FROM (
    SELECT user_id, (row_number() over (order by user_id)) AS rn FROM users
) idx
JOIN first f ON f.rn = ((idx.rn - 1) % 10) + 1
JOIN last l  ON l.rn = ((idx.rn - 1) % 10) + 1
WHERE u.user_id = idx.user_id;

-- Синхронизация последовательности (если нужно)
-- SELECT setval(pg_get_serial_sequence('users','user_id'), (SELECT MAX(user_id) FROM users));

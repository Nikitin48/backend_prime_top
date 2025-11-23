# Примеры тестовых данных для Data Lake

Эта папка содержит примеры тестовых файлов для демонстрации работы модуля интеграции с Data Lake.

## Файлы

### Products (Продукты)
- `products_example.json` - пример JSON файла с продуктами

### Series (Серии)
- `series_example.json` - пример JSON файла с сериями продуктов

### Stocks (Остатки)
- `stocks_example.json` - пример JSON файла с остатками на складе

### Orders (Заказы)
- `orders_example.json` - пример JSON файла с заказами

## Использование

### Загрузка продуктов

```bash
curl -X POST \
  http://localhost:8000/api/admin/data-lake/upload/ \
  -H "Authorization: Token YOUR_ADMIN_TOKEN" \
  -F "file=@products_example.json" \
  -F "data_type=products"
```

### Загрузка серий

```bash
curl -X POST \
  http://localhost:8000/api/admin/data-lake/upload/ \
  -H "Authorization: Token YOUR_ADMIN_TOKEN" \
  -F "file=@series_example.json" \
  -F "data_type=series"
```

### Загрузка остатков

```bash
curl -X POST \
  http://localhost:8000/api/admin/data-lake/upload/ \
  -H "Authorization: Token YOUR_ADMIN_TOKEN" \
  -F "file=@stocks_example.json" \
  -F "data_type=stocks"
```

### Загрузка заказов

```bash
curl -X POST \
  http://localhost:8000/api/admin/data-lake/upload/ \
  -H "Authorization: Token YOUR_ADMIN_TOKEN" \
  -F "file=@orders_example.json" \
  -F "data_type=orders"
```

## Порядок загрузки

Рекомендуемый порядок загрузки данных:

1. **Products** - сначала загрузите продукты
2. **Series** - затем загрузите серии (требуют существующие продукты)
3. **Stocks** - затем остатки (требуют существующие серии)
4. **Orders** - наконец заказы (требуют существующие продукты, серии и клиентов)

## Проверка перед загрузкой

Используйте параметр `dry_run=true` для проверки данных без сохранения:

```bash
curl -X POST \
  http://localhost:8000/api/admin/data-lake/upload/ \
  -H "Authorization: Token YOUR_ADMIN_TOKEN" \
  -F "file=@products_example.json" \
  -F "data_type=products" \
  -F "dry_run=true"
```

## Примечания

- Убедитесь, что у вас есть административный токен
- Проверьте, что связанные данные уже существуют в базе (например, клиенты для заказов)
- Используйте `dry_run=true` для проверки перед реальной загрузкой
- Обратите внимание на форматы дат (YYYY-MM-DD)


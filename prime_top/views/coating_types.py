from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import CoatingTypes


@require_GET
def coating_types_view(request):
    """
    Получить список всех категорий типов покрытий (coating types).
    
    Возвращает все доступные категории типов покрытий, отсортированные
    по номенклатуре. В будущем количество категорий может увеличиваться.
    
    Query параметры:
        - sort: порядок сортировки (по умолчанию: nomenclature)
                 Возможные значения: 'id', 'name', 'nomenclature', '-id', '-name', '-nomenclature'
    
    Returns:
        JSON response с полем 'count' (количество категорий) и 'results' (список категорий)
    """
    qs = CoatingTypes.objects.all()
    
    sort = request.GET.get("sort", "nomenclature")
    valid_sort_fields = {
        "id", "-id",
        "name", "-name",
        "nomenclature", "-nomenclature",
    }
    
    sort_mapping = {
        "id": "coating_types_id",
        "-id": "-coating_types_id",
        "name": "coating_type_name",
        "-name": "-coating_type_name",
        "nomenclature": "coating_type_nomenclatura",
        "-nomenclature": "-coating_type_nomenclatura",
    }
    
    if sort in valid_sort_fields:
        qs = qs.order_by(sort_mapping[sort])
    else:
        qs = qs.order_by("coating_type_nomenclatura")
    
    results = [
        {
            "id": coating_type.coating_types_id,
            "name": coating_type.coating_type_name,
            "nomenclature": coating_type.coating_type_nomenclatura,
        }
        for coating_type in qs
    ]
    
    return JsonResponse({
        "count": len(results),
        "results": results,
    })


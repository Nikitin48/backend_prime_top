from .auth import login_view, register_view
from .cart import (
    cart_checkout_view,
    cart_clear_view,
    cart_item_add_view,
    cart_item_detail_view,
    cart_view,
)
from .analyses import analyses_view
from .coating_types import coating_types_view
from .products import product_detail_view, products_search_view, products_view, top_products_view
from .series import series_view
from .stocks import available_stocks_view, stocks_view
from .clients import (
    client_detail_view,
    client_orders_detail,
    client_orders_summary,
    clients_view,
    client_users_view,
)
from .orders import order_detail_view, orders_view
from .personal import (
    my_order_detail_view,
    my_orders_all_view,
    my_orders_current_view,
    my_orders_history_view,
    my_stocks_view,
)
from .admin import (
    admin_analyses_create_or_update,
    admin_coating_types_create,
    admin_coating_types_update,
    admin_orders_detail,
    admin_orders_list,
    admin_products_create,
    admin_products_update,
    admin_series_create,
    admin_series_update,
    admin_stocks_create_or_update,
    admin_stocks_delete,
    admin_stocks_list,
    admin_stocks_update,
    admin_users_list,
    admin_users_update,
)
from .admin_analytics import (
    admin_analytics_top_coating_types,
    admin_analytics_top_products,
    admin_analytics_top_series,
)

__all__ = [
    "register_view",
    "login_view",
    "clients_view",
    "client_detail_view",
    "client_orders_summary",
    "client_orders_detail",
    "client_users_view",
    "products_view",
    "product_detail_view",
    "products_search_view",
    "coating_types_view",
    "series_view",
    "stocks_view",
    "available_stocks_view",
    "analyses_view",
    "top_products_view",
    "orders_view",
    "order_detail_view",
    "my_orders_current_view",
    "my_orders_history_view",
    "my_orders_all_view",
    "my_order_detail_view",
    "my_stocks_view",
    "cart_view",
    "cart_item_add_view",
    "cart_item_detail_view",
    "cart_checkout_view",
    "cart_clear_view",
    "admin_products_create",
    "admin_products_update",
    "admin_series_create",
    "admin_series_update",
    "admin_stocks_create_or_update",
    "admin_stocks_delete",
    "admin_stocks_list",
    "admin_stocks_update",
    "admin_analyses_create_or_update",
    "admin_users_list",
    "admin_users_update",
    "admin_coating_types_create",
    "admin_coating_types_update",
    "admin_orders_list",
    "admin_orders_detail",
    "admin_analytics_top_products",
    "admin_analytics_top_series",
    "admin_analytics_top_coating_types",
]


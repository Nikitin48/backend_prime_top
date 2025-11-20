from .auth import login_view, register_view
from .cart import (
    cart_checkout_view,
    cart_clear_view,
    cart_item_add_view,
    cart_item_detail_view,
    cart_view,
)
from .catalog import (
    analyses_view,
    coating_types_view,
    product_detail_view,
    products_view,
    series_view,
    stocks_view,
)
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
    "coating_types_view",
    "series_view",
    "stocks_view",
    "analyses_view",
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
]


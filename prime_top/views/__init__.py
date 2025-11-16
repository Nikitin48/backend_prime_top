from .auth import login_view, register_view
from .catalog import analyses_view, products_view, series_view, stocks_view
from .clients import (
    client_detail_view,
    client_orders_detail,
    client_orders_summary,
    clients_view,
)
from .orders import order_detail_view, orders_view
from .personal import (
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
    "products_view",
    "series_view",
    "stocks_view",
    "analyses_view",
    "orders_view",
    "order_detail_view",
    "my_orders_current_view",
    "my_orders_history_view",
    "my_stocks_view",
]


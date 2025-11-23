from django.urls import path

from . import views

app_name = "prime_top"

urlpatterns = [
    # Bot endpoints
    path("bot/link/", views.bot_link_view, name="bot-link"),
    path("bot/unlink/", views.bot_unlink_view, name="bot-unlink"),
    path("bot/orders/", views.bot_orders_view, name="bot-orders"),
    path("bot/orders/<int:order_id>/", views.bot_order_detail_view, name="bot-order-detail"),
    path("bot/profile/", views.bot_profile_view, name="bot-profile"),
    path("auth/register/", views.register_view, name="register"),
    path("auth/login/", views.login_view, name="login"),
    path("clients/", views.clients_view, name="clients"),
    path("clients/<int:client_id>/", views.client_detail_view, name="client-detail"),
    path("clients/<int:client_id>/orders/summary/", views.client_orders_summary, name="client-orders-summary"),
    path("clients/<int:client_id>/orders/", views.client_orders_detail, name="client-orders-detail"),
    path("clients/<int:client_id>/users/", views.client_users_view, name="client-users"),
    path("me/orders/", views.my_orders_all_view, name="my-orders-all"),
    path("me/orders/current/", views.my_orders_current_view, name="my-orders-current"),
    path("me/orders/history/", views.my_orders_history_view, name="my-orders-history"),
    path("me/orders/<int:order_id>/", views.my_order_detail_view, name="my-order-detail"),
    path("me/stocks/", views.my_stocks_view, name="my-stocks"),
    path("me/cart/", views.cart_view, name="cart"),
    path("me/cart/items/", views.cart_item_add_view, name="cart-item-add"),
    path("me/cart/items/<int:cart_item_id>/", views.cart_item_detail_view, name="cart-item-detail"),
    path("me/cart/checkout/", views.cart_checkout_view, name="cart-checkout"),
    path("me/cart/clear/", views.cart_clear_view, name="cart-clear"),
    path("products/", views.products_view, name="products"),
    path("products/top/", views.top_products_view, name="products-top"),
    path("products/search/", views.products_search_view, name="products-search"),
    path("products/<int:product_id>/", views.product_detail_view, name="product-detail"),
    path("coating-types/", views.coating_types_view, name="coating-types"),
    path("series/", views.series_view, name="series"),
    path("stocks/", views.stocks_view, name="stocks"),
    path("stocks/available/", views.available_stocks_view, name="stocks-available"),
    path("analyses/", views.analyses_view, name="analyses"),
    path("orders/", views.orders_view, name="orders"),
    path("orders/<int:order_id>/", views.order_detail_view, name="order-detail"),
    # Admin endpoints
    path("admin/products/", views.admin_products_create, name="admin-products-create"),
    path("admin/products/<int:product_id>/", views.admin_products_update, name="admin-products-update"),
    path("admin/series/", views.admin_series_create, name="admin-series-create"),
    path("admin/series/<int:series_id>/", views.admin_series_update, name="admin-series-update"),
    path("admin/stocks/", views.admin_stocks_list, name="admin-stocks-list"),
    path("admin/stocks/<int:stocks_id>/", views.admin_stocks_update, name="admin-stocks-update"),
    path("admin/stocks/<int:stocks_id>/delete/", views.admin_stocks_delete, name="admin-stocks-delete"),
    path("admin/analyses/<int:series_id>/", views.admin_analyses_create_or_update, name="admin-analyses-create-update"),
    path("admin/users/", views.admin_users_list, name="admin-users-list"),
    path("admin/users/<int:user_id>/", views.admin_users_update, name="admin-users-update"),
    path("admin/coating-types/", views.admin_coating_types_create, name="admin-coating-types-create"),
    path("admin/coating-types/<int:coating_type_id>/", views.admin_coating_types_update, name="admin-coating-types-update"),
    path("admin/orders/", views.admin_orders_list, name="admin-orders-list"),
    path("admin/orders/<int:order_id>/", views.admin_orders_detail, name="admin-orders-detail"),
    # Admin analytics endpoints
    path("admin/analytics/top-products/", views.admin_analytics_top_products, name="admin-analytics-top-products"),
    path("admin/analytics/top-series/", views.admin_analytics_top_series, name="admin-analytics-top-series"),
    path("admin/analytics/top-coating-types/", views.admin_analytics_top_coating_types, name="admin-analytics-top-coating-types"),
]


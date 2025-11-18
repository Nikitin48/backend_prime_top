from django.urls import path

from . import views

app_name = "prime_top"

urlpatterns = [
    path("auth/register/", views.register_view, name="register"),
    path("auth/login/", views.login_view, name="login"),
    path("clients/", views.clients_view, name="clients"),
    path("clients/<int:client_id>/", views.client_detail_view, name="client-detail"),
    path("clients/<int:client_id>/orders/summary/", views.client_orders_summary, name="client-orders-summary"),
    path("clients/<int:client_id>/orders/", views.client_orders_detail, name="client-orders-detail"),
    path("me/orders/", views.my_orders_all_view, name="my-orders-all"),
    path("me/orders/current/", views.my_orders_current_view, name="my-orders-current"),
    path("me/orders/history/", views.my_orders_history_view, name="my-orders-history"),
    path("me/orders/<int:order_id>/", views.my_order_detail_view, name="my-order-detail"),
    path("me/stocks/", views.my_stocks_view, name="my-stocks"),
    path("products/", views.products_view, name="products"),
    path("products/<int:product_id>/", views.product_detail_view, name="product-detail"),
    path("coating-types/", views.coating_types_view, name="coating-types"),
    path("series/", views.series_view, name="series"),
    path("stocks/", views.stocks_view, name="stocks"),
    path("analyses/", views.analyses_view, name="analyses"),
    path("orders/", views.orders_view, name="orders"),
    path("orders/<int:order_id>/", views.order_detail_view, name="order-detail"),
]


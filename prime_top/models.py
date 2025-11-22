# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Analyses(models.Model):
    series = models.OneToOneField('Series', models.DO_NOTHING, primary_key=True, db_column='series_id')
    analyses_blesk_pri_60_grad = models.FloatField(blank=True, null=True)
    analyses_uslovnaya_vyazkost = models.FloatField(blank=True, null=True)
    analyses_delta_e = models.FloatField(blank=True, null=True)
    analyses_delta_l = models.FloatField(blank=True, null=True)
    analyses_delta_a = models.FloatField(blank=True, null=True)
    analyses_color_diff_deltae_d8 = models.FloatField(blank=True, null=True)
    analyses_delta_b = models.FloatField(blank=True, null=True)
    analyses_vremya_sushki = models.FloatField(blank=True, null=True)
    analyses_pikovaya_temperatura = models.FloatField(blank=True, null=True)
    analyses_tolschina_dlya_grunta = models.FloatField(blank=True, null=True)
    analyses_adgeziya = models.FloatField(blank=True, null=True)
    analyses_stoikost_k_rastvor = models.FloatField(blank=True, null=True)
    analyses_viz_kontrol_poverh = models.CharField(max_length=15, blank=True, null=True)
    analyses_vneshnii_vid = models.CharField(max_length=31, blank=True, null=True)
    analyses_kolvo_vykr_s_partii = models.FloatField(blank=True, null=True)
    analyses_unnamed_16 = models.FloatField(blank=True, null=True)
    analyses_stepen_peretira = models.FloatField(blank=True, null=True)
    analyses_tverd_vesches_po_v = models.FloatField(blank=True, null=True)
    analyses_grunt = models.CharField(max_length=30, blank=True, null=True)
    analyses_tolsch_plenki_zhidk = models.FloatField(blank=True, null=True)
    analyses_tolsch_dly_em_lak_ch = models.FloatField(blank=True, null=True)
    analyses_teoreticheskii_rashod = models.FloatField(blank=True, null=True)
    analyses_prochnost_pri_izgibe = models.FloatField(blank=True, null=True)
    analyses_stoikost_k_obrat_udaru = models.FloatField(blank=True, null=True)
    analyses_tverdost_po_karandashu = models.CharField(max_length=2, blank=True, null=True)
    analyses_prochn_rastyazh_po_er = models.FloatField(blank=True, null=True)
    analyses_blesk = models.FloatField(blank=True, null=True)
    analyses_plotnost = models.FloatField(blank=True, null=True)
    analyses_mass_dolya_nelet_vesh = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'analyses'


class Clients(models.Model):
    client_id = models.AutoField(primary_key=True)
    client_name = models.CharField(max_length=20)
    client_email = models.CharField(max_length=30)

    class Meta:
        managed = False
        db_table = 'clients'


class Cart(models.Model):
    cart_id = models.AutoField(primary_key=True)
    user = models.OneToOneField('Users', models.DO_NOTHING, db_column='user_id')
    cart_created_at = models.DateTimeField()
    cart_updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'cart'


class CartItem(models.Model):
    cart_item_id = models.AutoField(primary_key=True)
    cart = models.ForeignKey('Cart', models.DO_NOTHING, db_column='cart_id')
    product = models.ForeignKey('Products', models.DO_NOTHING, db_column='product_id')
    series = models.ForeignKey('Series', models.DO_NOTHING, db_column='series_id', blank=True, null=True)
    cart_item_quantity = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'cart_item'


class CoatingTypes(models.Model):
    coating_types_id = models.AutoField(primary_key=True)
    coating_type_name = models.CharField(max_length=40)
    coating_type_nomenclatura = models.CharField(max_length=40)

    class Meta:
        managed = False
        db_table = 'coating_types'


class OrderStatusHistory(models.Model):
    order_status_history_id = models.AutoField(primary_key=True)
    orders = models.ForeignKey('Orders', models.DO_NOTHING)
    order_status_history_from_stat = models.CharField(max_length=30)
    order_status_history_to_status = models.CharField(max_length=30)
    order_status_history_chang_at = models.CharField(max_length=30)
    order_status_history_note = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'order_status_history'


class Orders(models.Model):
    orders_id = models.AutoField(primary_key=True)
    client = models.ForeignKey(Clients, models.DO_NOTHING)
    orders_status = models.CharField(max_length=30)
    orders_created_at = models.DateField()
    orders_shipped_at = models.DateField(blank=True, null=True)
    orders_delivered_at = models.DateField(blank=True, null=True)
    orders_cancel_reason = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'orders'


class OrdersItems(models.Model):
    order_items_id = models.AutoField(primary_key=True)
    orders = models.ForeignKey(Orders, models.DO_NOTHING)
    product = models.ForeignKey('Products', models.DO_NOTHING)
    series = models.ForeignKey('Series', models.DO_NOTHING, blank=True, null=True)
    order_items_count = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'orders_items'


class Products(models.Model):
    product_id = models.AutoField(primary_key=True)
    coating_types = models.ForeignKey(CoatingTypes, models.DO_NOTHING)
    color = models.IntegerField()
    product_name = models.CharField(max_length=40)
    product_price = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'products'


class Series(models.Model):
    series_id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Products, models.DO_NOTHING)
    series_name = models.CharField(max_length=20, blank=True, null=True)
    series_production_date = models.DateField(blank=True, null=True)
    series_expire_date = models.DateField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'series'


class Stocks(models.Model):
    stocks_id = models.AutoField(primary_key=True)
    client = models.ForeignKey(Clients, models.DO_NOTHING, blank=True, null=True)
    series = models.ForeignKey(Series, models.DO_NOTHING, blank=True, null=True)
    stocks_is_reserved_for_client = models.BooleanField()
    stocks_update_at = models.DateField()
    stocks_count = models.FloatField()

    class Meta:
        managed = False
        db_table = 'stocks'


class Users(models.Model):
    user_id = models.AutoField(primary_key=True)
    client = models.ForeignKey(Clients, models.DO_NOTHING)
    user_email = models.CharField(max_length=30)
    user_password_hash = models.CharField(max_length=255)
    user_is_active = models.BooleanField()
    user_created_at = models.DateField()
    user_name = models.CharField(max_length=50, blank=True, null=True)
    user_surname = models.CharField(max_length=50, blank=True, null=True)
    user_is_admin = models.BooleanField(default=False, db_column='user_is_admin')

    class Meta:
        managed = False
        db_table = 'users'

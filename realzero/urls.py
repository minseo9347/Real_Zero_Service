from django.urls import path
from . import views
from .views import ranking_view, community_content

urlpatterns = [
    path('', views.index, name='index'),
    path('ranking/', ranking_view, name='ranking'),
    path('product/<int:id>/', views.product_detail, name='product_detail'),
    path('community/', views.community_content, name='community'),
    path('search/', views.search, name='search'),
]
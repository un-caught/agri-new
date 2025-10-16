from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'referrals', views.AdminReferralViewSet, basename='admin-referral')
router.register(r'referral-earnings', views.AdminReferralEarningViewSet, basename='admin-referral-earning')
router.register(r'referral-codes', views.AdminReferralCodeViewSet, basename='admin-referral-code')

urlpatterns = [
    path('', include(router.urls)),
    path('all-transactions/', views.all_transactions, name='all-transactions'),
    path("transactions/<str:pk>/", views.update_transaction, name="update-transaction"),
]

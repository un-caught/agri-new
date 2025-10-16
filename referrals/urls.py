from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'codes', views.ReferralCodeViewSet, basename='referral-code')
router.register(r'referrals', views.ReferralViewSet, basename='referral')
router.register(r'earnings', views.ReferralEarningViewSet, basename='referral-earning')
router.register(r'bonuses', views.ReferralBonusViewSet, basename='referral-bonus')

# Admin router
admin_router = DefaultRouter()
admin_router.register(r'codes', views.AdminReferralCodeViewSet, basename='admin-referral-code')
admin_router.register(r'referrals', views.AdminReferralViewSet, basename='admin-referral')
admin_router.register(r'earnings', views.AdminReferralEarningViewSet, basename='admin-referral-earning')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/', include(admin_router.urls)),
    path('validate-code/', views.ValidateReferralCodeView.as_view(), name='validate-referral-code'),
    path('dashboard/', views.ReferralDashboardView.as_view(), name='referral-dashboard'),
    path('set-referrer/', views.SetReferrerView.as_view(), name='set-referrer'),
]

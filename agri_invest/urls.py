"""
URL configuration for agri_invest project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from users.views import google_oauth_login, google_oauth_callback, custom_activation, submit_referral_code, submit_kyc, get_user_profile, get_user_profile_details
from users.profile_views import update_profile_picture
from rest_framework.routers import DefaultRouter
from users.views import NotificationViewSet, AdminUserViewSet, bank_account, FrontendAppView
from ecommerce.views import ProductViewSet, OrderViewSet, CartViewSet, CartItemView, InitializePaymentView, VerifyPaymentView, PaystackWebhookView, PaymentCallbackView
from storage.views import StoragePlanListView, StoragePlanDetailView, purchase_storage_plan,  MyInvestmentsView, InvestmentDetailView, dashboard_stats, verify_payment, paystack_webhook, mature_investment, AdminStorageInvestmentsView, AdminStorageInvestmentDetailView
from django.conf import settings
from django.conf.urls.static import static

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register('products', ProductViewSet, basename='products')
router.register('orders', OrderViewSet, basename='orders')
router.register(r'cart', CartViewSet, basename='cart')
router.register(r'adminusers', AdminUserViewSet, basename='admin-users')


# urlpatterns = [
#     path('superadmin/', admin.site.urls),
#     # Custom referral code submission endpoint must come before djoser includes
#     path('api/auth/submit-referral/', submit_referral_code, name='submit_referral_code'),
#     path('api/auth/', include('djoser.urls')),
#     path('api/auth/', include('djoser.urls.jwt')),
#     path('api/user/kyc/', submit_kyc, name='submit_kyc'),
#     path('api/user/profile/', get_user_profile, name='get_user_profile'),
#     path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
#     path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
#     # Custom Google OAuth endpoints
#     path('api/auth/google/', google_oauth_login, name='google_oauth_login'),
#     path('api/auth/google/callback/', google_oauth_callback, name='google_oauth_callback'),
#     # Custom activation endpoint
#     path('activate/<str:uid>/<str:token>/', custom_activation, name='custom_activation'),
#     # Social Auth URLs - this will handle /api/auth/login/google/ and other social auth endpoints
#     path('api/auth/', include('social_django.urls')),
#     # Investment APIs
#     path('api/investments/', include('investments.urls')),
#     # Referral APIs
#     path('api/referrals/', include('referrals.urls')),
#     path('api/', include(router.urls)),
#     path('api/cart/items/', CartItemView.as_view(), name='cart-items'),
#     path('api/payments/initialize/', InitializePaymentView.as_view(), name='initialize_payment'),
#     path('api/payments/verify/', VerifyPaymentView.as_view(), name='verify_payment'),
#     path('api/payments/webhook/', PaystackWebhookView.as_view(), name='paystack_webhook'),
#     path('api/admin/', include('admin_api.urls')),
#     # Storage Plans
#     path('api/storage/storage-plans/', StoragePlanListView.as_view(), name='storage-plans-list'),
#     path('api/storage/storage-plans/<uuid:pk>/', StoragePlanDetailView.as_view(), name='storage-plan-detail'),
#     path('api/storage/storage-plans/purchase/', purchase_storage_plan, name='purchase-storage-plan'),
    
#     # Investments
#     path('api/storage/my-investments/', MyInvestmentsView.as_view(), name='my-investments'),
#     path('api/storage/investments/<uuid:pk>/', InvestmentDetailView.as_view(), name='investment-detail'),
    
#     # Dashboard
#     path('api/storage/dashboard/stats/', dashboard_stats, name='dashboard-stats'),
    
#     # Payment
#     path('api/storage/payment/verify/', verify_payment, name='verify-payment'),
#     path('api/storage/webhooks/paystack/', paystack_webhook, name='paystack-webhook'),
#     path('api/storage/investments/<uuid:investment_id>/complete/', mature_investment, name='mature-investment'),
#     path('api/bank-account/', bank_account, name='bank-account'),
#     re_path(r"^.*$", FrontendAppView.as_view(), name="frontend"),
# ]
urlpatterns = [
    # ===== ADMIN =====
    path('superadmin/', admin.site.urls),

    # ===== AUTH =====
    path('api/auth/submit-referral/', submit_referral_code, name='submit_referral_code'),
    path('api/auth/', include('djoser.urls')),
    path('api/auth/', include('djoser.urls.jwt')),
    path('api/user/kyc/', submit_kyc, name='submit_kyc'),
    path('api/user/profile/', get_user_profile, name='get_user_profile'),
    path('api/user/profile-details/', get_user_profile_details, name='get_user_profile_details'),
    path('api/user/profile-picture/', update_profile_picture, name='update_profile_picture'),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # ===== GOOGLE OAUTH =====
    path('api/auth/google/', google_oauth_login, name='google_oauth_login'),
    path('api/auth/google/callback/', google_oauth_callback, name='google_oauth_callback'),

    # ===== ACTIVATION =====
    path('activate/<str:uid>/<str:token>/', custom_activation, name='custom_activation'),

    # ===== SOCIAL AUTH (optional) =====
    path('api/auth/social/', include('social_django.urls', namespace='social')),

    # ===== INVESTMENTS =====
    path('api/investments/', include('investments.urls')),
    path('api/storage/my-investments/', MyInvestmentsView.as_view(), name='my-investments'),
    path('api/storage/investments/<uuid:pk>/', InvestmentDetailView.as_view(), name='investment-detail'),
    path('api/storage/dashboard/stats/', dashboard_stats, name='dashboard-stats'),
    path('api/storage/investments/<uuid:investment_id>/complete/', mature_investment, name='mature-investment'),

    # ===== STORAGE =====
    path('api/storage/storage-plans/', StoragePlanListView.as_view(), name='storage-plans-list'),
    path('api/storage/storage-plans/<uuid:pk>/', StoragePlanDetailView.as_view(), name='storage-plan-detail'),
    path('api/storage/storage-plans/purchase/', purchase_storage_plan, name='purchase-storage-plan'),
    path('api/storage/admin/investments/', AdminStorageInvestmentsView.as_view(), name='admin-storage-investments'),
    path('api/storage/admin/investments/<uuid:pk>/', AdminStorageInvestmentDetailView.as_view(), name='admin-storage-investment-detail'),
    path('api/storage/payment/verify/', verify_payment, name='verify-payment'),
    path('api/storage/webhooks/paystack/', paystack_webhook, name='paystack-webhook'),

    # ===== PAYMENTS =====
    path('api/payments/initialize/', InitializePaymentView.as_view(), name='initialize_payment'),
    path('api/payments/verify/', VerifyPaymentView.as_view(), name='verify_payment'),
    path('api/payments/webhook/', PaystackWebhookView.as_view(), name='paystack_webhook'),
    path('api/payments/callback/', PaymentCallbackView.as_view(), name='payment_callback'),

    # ===== CART =====
    path('api/cart/items/', CartItemView.as_view(), name='cart-items'),
    path('api/cart/items/<uuid:item_id>/', CartItemView.as_view(), name='cart-item-detail'),

    # ===== BANK ACCOUNT =====
    path('api/bank-account/', bank_account, name='bank-account'),

    # ===== ADMIN API =====
    path('api/admin/', include('admin_api.urls')),

    # ===== REFERRALS =====
    path('api/referrals/', include('referrals.urls')),

    # ===== OTHER ROUTER URLS =====
    path('api/', include(router.urls)),

    # ===== CATCH-ALL FRONTEND =====
    # This must be LAST so it doesn’t override any API or admin routes
    re_path(r'^.*$', FrontendAppView.as_view(), name='frontend'),
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
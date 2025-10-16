from rest_framework import serializers
from .models import ReferralCode, Referral, ReferralEarning, ReferralBonus
from django.db.models import Sum, Count

class ReferralCodeSerializer(serializers.ModelSerializer):
    """Serializer for ReferralCode model"""

    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    referrals_count = serializers.SerializerMethodField()
    active_referrals = serializers.SerializerMethodField()
    total_earnings = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCode
        fields = [
            'id', 'user', 'user_email', 'user_name', 'code', 'is_active',
            'referrals_count', 'active_referrals', 'total_earnings',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'code']

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.email

    def get_referrals_count(self, obj):
        return obj.referrals.count()

    def get_active_referrals(self, obj):
        return obj.referrals.filter(status='active').count()

    def get_total_earnings(self, obj):
        return ReferralEarning.objects.filter(
            referral__referral_code=obj,
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0

class ReferralSerializer(serializers.ModelSerializer):
    """Serializer for Referral model"""

    referrer_email = serializers.CharField(source='referrer.email', read_only=True)
    referrer_name = serializers.SerializerMethodField()
    referred_user_email = serializers.CharField(source='referred_user.email', read_only=True)
    referred_user_name = serializers.SerializerMethodField()
    referral_code_code = serializers.CharField(source='referral_code.code', read_only=True)
    earnings = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = [
            'id', 'referrer', 'referrer_email', 'referrer_name', 'referred_user', 'referred_user_email',
            'referred_user_name', 'referral_code', 'referral_code_code', 'status',
            'commission_rate', 'earnings', 'created_at', 'activated_at', 'completed_at'
        ]
        read_only_fields = ['referrer', 'referral_code']

    def get_referrer_name(self, obj):
        return f"{obj.referrer.first_name} {obj.referrer.last_name}".strip() or obj.referrer.email

    def get_referred_user_name(self, obj):
        return f"{obj.referred_user.first_name} {obj.referred_user.last_name}".strip() or obj.referred_user.email

    def get_earnings(self, obj):
        return ReferralEarning.objects.filter(
            referral=obj,
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0

class ReferralEarningSerializer(serializers.ModelSerializer):
    """Serializer for ReferralEarning model"""

    referral_referrer_email = serializers.CharField(source='referral.referrer.email', read_only=True)
    referrer_name = serializers.SerializerMethodField()
    referred_user_email = serializers.CharField(source='referral.referred_user.email', read_only=True)
    referred_user_name = serializers.SerializerMethodField()
    investment_package_name = serializers.CharField(source='investment.package.name', read_only=True)
    investment_amount = serializers.DecimalField(source='investment.amount', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = ReferralEarning
        fields = [
            'id', 'referral', 'referral_referrer_email', 'referrer_name', 'referred_user_email',
            'referred_user_name', 'investment', 'investment_package_name',
            'investment_amount', 'amount', 'commission_rate', 'status', 'created_at', 'paid_at'
        ]
        read_only_fields = ['referral', 'investment', 'amount', 'commission_rate']

    def get_referrer_name(self, obj):
        return f"{obj.referral.referrer.first_name} {obj.referral.referrer.last_name}".strip() or obj.referral.referrer.email

    def get_referred_user_name(self, obj):
        return f"{obj.referral.referred_user.first_name} {obj.referral.referred_user.last_name}".strip() or obj.referral.referred_user.email

class ReferralBonusSerializer(serializers.ModelSerializer):
    """Serializer for ReferralBonus model"""
    
    class Meta:
        model = ReferralBonus
        fields = [
            'id', 'name', 'description', 'min_referrals', 'min_investment_amount',
            'bonus_amount', 'bonus_type', 'is_active', 'created_at'
        ]

class ReferralStatsSerializer(serializers.Serializer):
    """Serializer for referral statistics"""
    
    total_referrals = serializers.IntegerField()
    active_referrals = serializers.IntegerField()
    completed_referrals = serializers.IntegerField()
    pending_referrals = serializers.IntegerField()
    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    this_month_earnings = serializers.DecimalField(max_digits=12, decimal_places=2) 
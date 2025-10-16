from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from investments.models import Transaction as InvestmentTransaction
from storage.models import PaymentTransaction as StorageTransaction
from ecommerce.models import Order
from django.utils.timezone import localtime
from rest_framework import status
from referrals.models import Referral, ReferralEarning, ReferralCode
from django.db.models import Sum, Count

# Import referral admin viewsets
from referrals.views import AdminReferralViewSet, AdminReferralEarningViewSet, AdminReferralCodeViewSet

@api_view(['GET'])
@permission_classes([IsAdminUser])
def all_transactions(request):
    transactions = []

    # Investment transactions
    for tx in InvestmentTransaction.objects.select_related('user').all():
        transactions.append({
            'id': f"INV-{tx.id}",
            'type': 'Investment',
            'user': tx.user.get_full_name() or tx.user.username,
            'email': tx.user.email,
            'amount': tx.amount,
            'status': tx.status,
            'date': localtime(tx.created_at).strftime('%Y-%m-%d %H:%M'),
        })

    # Storage transactions
    for tx in StorageTransaction.objects.select_related('investment__user').all():
        transactions.append({
            'id': f"STO-{tx.id}",
            'type': 'Storage',
            'user': tx.investment.user.get_full_name() or tx.investment.user.username,
            'email': tx.investment.user.email,
            'amount': tx.amount,
            'status': tx.status,
            'date': localtime(tx.created_at).strftime('%Y-%m-%d %H:%M'),
        })

    # E-commerce orders
    for order in Order.objects.all():
        transactions.append({
            'id': f"ORD-{order.id}",
            'type': 'E-commerce',
            'user': f"{order.user.first_name} {order.user.last_name}".strip() or order.user.username,
            'email': order.email,
            'amount': order.total_amount,
            'status': order.status,
            'date': localtime(order.created_at).strftime('%Y-%m-%d %H:%M'),
        })

    # Sort by date descending
    transactions.sort(key=lambda x: x['date'], reverse=True)

    return Response(transactions)


@api_view(['PUT'])
@permission_classes([IsAdminUser])
def update_transaction(request, pk):
    """
    Update a transaction (investment, storage, or e-commerce) based on ID prefix.
    Expected payload: {"amount": ..., "status": "..."}
    """
    try:
        # Determine type by prefix
        if pk.startswith("INV-"):
            tx_id = pk.replace("INV-", "")
            transaction = InvestmentTransaction.objects.get(id=tx_id)
            if "amount" in request.data:
                transaction.amount = request.data["amount"]
            if "status" in request.data:
                transaction.status = request.data["status"]
            transaction.save()
            return Response({"message": "Investment transaction updated successfully"})

        elif pk.startswith("STO-"):
            tx_id = pk.replace("STO-", "")
            transaction = StorageTransaction.objects.get(id=tx_id)
            if "amount" in request.data:
                transaction.amount = request.data["amount"]
            if "status" in request.data:
                transaction.status = request.data["status"]
            transaction.save()
            return Response({"message": "Storage transaction updated successfully"})

        elif pk.startswith("ORD-"):
            tx_id = pk.replace("ORD-", "")
            order = Order.objects.get(id=tx_id)
            if "amount" in request.data:
                order.total_amount = request.data["amount"]
            if "status" in request.data:
                order.status = request.data["status"]
            order.save()
            return Response({"message": "E-commerce order updated successfully"})

        else:
            return Response({"error": "Invalid transaction ID format"}, status=status.HTTP_400_BAD_REQUEST)

    except (InvestmentTransaction.DoesNotExist, StorageTransaction.DoesNotExist, Order.DoesNotExist):
        return Response({"error": "Transaction not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_referrals(request):
    """
    Get all referrals for admin
    """
    referrals = Referral.objects.select_related('referrer', 'referred_user', 'referral_code').all()

    data = []
    for referral in referrals:
        # Calculate earnings for this referral
        earnings = ReferralEarning.objects.filter(referral=referral).aggregate(
            total=Sum('amount')
        )['total'] or 0

        data.append({
            'id': referral.id,
            'referrer': {
                'id': referral.referrer.id,
                'email': referral.referrer.email,
                'name': f"{referral.referrer.first_name} {referral.referrer.last_name}".strip() or referral.referrer.email
            },
            'referred': {
                'id': referral.referred_user.id,
                'email': referral.referred_user.email,
                'name': f"{referral.referred_user.first_name} {referral.referred_user.last_name}".strip() or referral.referred_user.email
            },
            'referral_code': referral.referral_code.code,
            'status': referral.status,
            'commission_rate': float(referral.commission_rate),
            'earnings': float(earnings),
            'created_at': referral.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'activated_at': referral.activated_at.strftime('%Y-%m-%d %H:%M:%S') if referral.activated_at else None,
            'completed_at': referral.completed_at.strftime('%Y-%m-%d %H:%M:%S') if referral.completed_at else None,
        })

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_referral_earnings(request):
    """
    Get all referral earnings for admin
    """
    earnings = ReferralEarning.objects.select_related(
        'referral__referrer',
        'referral__referred_user',
        'investment'
    ).all()

    data = []
    for earning in earnings:
        data.append({
            'id': earning.id,
            'referrer': {
                'id': earning.referral.referrer.id,
                'email': earning.referral.referrer.email,
                'name': f"{earning.referral.referrer.first_name} {earning.referral.referrer.last_name}".strip() or earning.referral.referrer.email
            },
            'referred': {
                'id': earning.referral.referred_user.id,
                'email': earning.referral.referred_user.email,
                'name': f"{earning.referral.referred_user.first_name} {earning.referral.referred_user.last_name}".strip() or earning.referral.referred_user.email
            },
            'investment': {
                'id': earning.investment.id,
                'amount': float(earning.investment.amount),
                'package_name': earning.investment.package.name if hasattr(earning.investment, 'package') else 'N/A'
            },
            'amount': float(earning.amount),
            'commission_rate': float(earning.commission_rate),
            'status': earning.status,
            'created_at': earning.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'paid_at': earning.paid_at.strftime('%Y-%m-%d %H:%M:%S') if earning.paid_at else None,
        })

    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_referral_codes(request):
    """
    Get all referral codes for admin
    """
    codes = ReferralCode.objects.select_related('user').all()

    data = []
    for code in codes:
        # Get referral stats for this code
        referrals_count = Referral.objects.filter(referral_code=code).count()
        active_referrals = Referral.objects.filter(referral_code=code, status='active').count()
        total_earnings = ReferralEarning.objects.filter(
            referral__referral_code=code,
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0

        data.append({
            'id': code.id,
            'user': {
                'id': code.user.id,
                'email': code.user.email,
                'name': f"{code.user.first_name} {code.user.last_name}".strip() or code.user.email
            },
            'code': code.code,
            'is_active': code.is_active,
            'referrals_count': referrals_count,
            'active_referrals': active_referrals,
            'total_earnings': float(total_earnings),
            'created_at': code.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': code.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    return Response(data)

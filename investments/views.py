from asyncio.log import logger
from django.shortcuts import render
from rest_framework import viewsets, status, permissions, serializers
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.conf import settings
import time
import requests
from rest_framework.decorators import api_view, permission_classes
from django.db.models import Q

from .models import InvestmentPackage, Investment, Transaction, Portfolio, Payment, WithdrawalRequest
from .serializers import (
    InvestmentPackageSerializer,
    InvestmentPackageDetailSerializer,
    InvestmentSerializer,
    InvestmentCreateSerializer,
    AdminInvestmentCreateSerializer,
    TransactionSerializer,
    PortfolioSerializer,
    UserInvestmentSummarySerializer,
    PaymentSerializer,
    PaymentCreateSerializer,
    CreateWithdrawalRequestSerializer,
    WithdrawalRequestSerializer
)

class InvestmentPackageViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for investment packages"""
    
    queryset = InvestmentPackage.objects.filter(status='active')  # type: ignore
    permission_classes = [permissions.AllowAny]
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InvestmentPackageDetailSerializer
        return InvestmentPackageSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by category
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by risk level
        risk_level = self.request.query_params.get('risk_level', None)
        if risk_level:
            queryset = queryset.filter(risk_level=risk_level)
        
        # Filter by minimum amount
        min_amount = self.request.query_params.get('min_amount', None)
        if min_amount:
            queryset = queryset.filter(min_amount__gte=min_amount)
        
        # Filter by maximum amount
        max_amount = self.request.query_params.get('max_amount', None)
        if max_amount:
            queryset = queryset.filter(max_amount__lte=max_amount)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get all available categories"""
        categories = InvestmentPackage.objects.values_list('category', flat=True).distinct()
        return Response(list(categories))
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get investment package statistics"""
        total_packages = InvestmentPackage.objects.filter(status='active').count()
        total_investments = Investment.objects.count()
        total_amount_invested = Investment.objects.aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        return Response({
            'total_packages': total_packages,
            'total_investments': total_investments,
            'total_amount_invested': total_amount_invested,
        })

class InvestmentViewSet(viewsets.ModelViewSet):
    """ViewSet for user investments"""

    permission_classes = [IsAuthenticated]
    filterset_fields = ['status']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvestmentCreateSerializer
        return InvestmentSerializer
    
    def get_queryset(self):
        return Investment.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def create(self, request, *args, **kwargs):
        if not request.user.is_kyc_complete:
            return Response(
                {'error': 'You must complete KYC verification before making investments'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        investment = serializer.save(user=request.user)
        # Use the full serializer for the response
        output_serializer = InvestmentSerializer(investment, context={'request': request})
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get user's active investments"""
        active_investments = self.get_queryset().filter(status='active')
        serializer = self.get_serializer(active_investments, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def completed(self, request):
        """Get user's completed investments"""
        completed_investments = self.get_queryset().filter(status='completed')
        serializer = self.get_serializer(completed_investments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def pending(self, request):
        """Get user's pending investments"""
        pending_investments = self.get_queryset().filter(status='pending')
        serializer = self.get_serializer(pending_investments, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get user's investment summary"""
        investments = self.get_queryset()
        
        total_invested = investments.aggregate(total=Sum('amount'))['total'] or 0
        total_returns = investments.filter(status='completed').aggregate(
            total=Sum('actual_return')
        )['total'] or 0
        active_investments = investments.filter(status='active').count()
        completed_investments = investments.filter(status='completed').count()
        
        return Response({
            'total_invested': total_invested,
            'total_returns': total_returns,
            'active_investments': active_investments,
            'completed_investments': completed_investments,
            'total_portfolio_value': total_invested + total_returns,
        })
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Mark investment as completed (frontend-triggered)"""
        investment = self.get_object()
        
        # Validation checks
        if investment.status != 'active':
            return Response(
                {'error': 'Only active investments can be completed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if timezone.now().date() < investment.end_date:
            return Response(
                {'error': 'Investment is not yet due for completion'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update status
        investment.status = 'completed'
        investment.completed_date = timezone.now()
        investment.save()
        
        # Clean up any cancelled payments (one-time operation)
        self.cleanup_cancelled_payments(investment)

        Payment.objects.filter(
            investment=investment,
            status='cancelled'
        ).delete()
        
        return Response({
            'success': True,
            'message': 'Investment marked as completed',
            'investment': InvestmentSerializer(investment).data
        })
    
    def cleanup_cancelled_payments(self, investment):
        """Delete any cancelled payments for this investment"""
        Payment.objects.filter(
            investment=investment,
            status='cancelled'
        ).delete()

    def cancel_pending_investments_for_package(self, package):
        """Cancel all pending investments for a package when slots are full"""
        pending_investments = Investment.objects.filter(
            package=package,
            status='pending'
        )

        for investment in pending_investments:
            # Set status to cancelled
            investment.status = 'cancelled'
            investment.save()

            # Create refund transaction
            Transaction.objects.create(
                user=investment.user,
                investment=investment,
                transaction_type='refund',
                amount=investment.amount,
                status='completed',
                description=f'Refund for cancelled investment in {package.name} (package full)'
            )

            # Delete the investment
            investment.delete()

    def list(self, request, *args, **kwargs):
        """List investments with one-time cleanup of cancelled investments"""
        if request.user.is_authenticated:
            # Delete cancelled investments that belong to this user
            deleted_count, _ = Investment.objects.filter(
                Q(user=request.user) & 
                Q(status='cancelled')
            ).delete()
            
            print(f"Deleted {deleted_count} cancelled investments for user {request.user.id}")

        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def withdrawable(self, request):
        """Get user's completed investments that haven't been withdrawn"""
        completed_investments = self.get_queryset().filter(
            status='completed',
            withdrawal_request__isnull=True
        )
        serializer = self.get_serializer(completed_investments, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an investment"""
        investment = self.get_object()
        
        if investment.status != 'pending':
            return Response(
                {'error': 'Only pending investments can be cancelled'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        investment.status = 'cancelled'
        investment.save()
        
        # Refund the amount
        Transaction.objects.create(
            user=request.user,
            investment=investment,
            transaction_type='refund',
            amount=investment.amount,
            status='completed',
            description=f'Refund for cancelled investment in {investment.package.name}'
        )
        
        # Update package available slots
        package = investment.package
        package.available_slots += 1
        package.save()
        
        # Delete the investment after refund and slot update
        investment.delete()
        
        return Response({'message': 'Investment cancelled and deleted successfully'})

class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for user transactions"""
    
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer
    
    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent transactions"""
        recent_transactions = self.get_queryset().order_by('-created_at')[:10]
        serializer = self.get_serializer(recent_transactions, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """Get transactions by type"""
        transaction_type = request.query_params.get('type')
        if transaction_type:
            transactions = self.get_queryset().filter(transaction_type=transaction_type)
        else:
            transactions = self.get_queryset()
        
        serializer = self.get_serializer(transactions, many=True)
        return Response(serializer.data)

class PortfolioViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for user portfolio"""
    
    permission_classes = [IsAuthenticated]
    serializer_class = PortfolioSerializer
    
    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user)
    
    def list(self, request, *args, **kwargs):
        """Get or create user portfolio"""
        portfolio, created = Portfolio.objects.get_or_create(user=request.user)
        portfolio.update_portfolio()  # Update portfolio data
        serializer = self.get_serializer(portfolio)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def performance(self, request):
        """Get portfolio performance over time"""
        # Get investments grouped by month
        investments = Investment.objects.filter(user=request.user)
        
        # Calculate monthly performance (simplified)
        performance_data = []
        for i in range(6):  # Last 6 months
            month_date = timezone.now().date() - timedelta(days=30*i)
            month_investments = investments.filter(
                investment_date__month=month_date.month,
                investment_date__year=month_date.year
            )
            
            total_invested = month_investments.aggregate(
                total=Sum('amount')
            )['total'] or 0
            
            performance_data.append({
                'month': month_date.strftime('%B %Y'),
                'invested': total_invested,
                'returns': 0,  # Simplified - would need actual return data
            })
        
        return Response(performance_data)
    
    @action(detail=False, methods=['get'])
    def allocation(self, request):
        """Get investment allocation by category"""
        investments = Investment.objects.filter(
            user=request.user,
            status='active'
        ).select_related('package')
        
        allocation = {}
        for investment in investments:
            category = investment.package.category
            if category not in allocation:
                allocation[category] = 0
            allocation[category] += float(investment.amount)
        
        return Response(allocation)

class PaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for payment transactions via Paystack"""

    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentCreateSerializer
        return PaymentSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()

        # Get Paystack settings
        paystack_secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        if not paystack_secret_key:
            payment.status = 'failed'
            payment.save()
            return Response({'error': 'Paystack is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Initialize Paystack transaction
        url = 'https://api.paystack.co/transaction/initialize'
        headers = {
            'Authorization': f'Bearer {paystack_secret_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'email': payment.user.email,
            'amount': int(payment.amount * 100),  # Convert to kobo
            'reference': payment.paystack_reference,
            'callback_url': f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')}/investment-payment-success",
            'metadata': {
                'investment_id': payment.investment.id,
                'user_id': payment.user.id,
                'package_name': payment.investment.package.name,
            }
        }

        try:
            response = requests.post(url, json=data, headers=headers)
            response_data = response.json()

            if response_data.get('status'):
                # Update payment with Paystack data
                payment.paystack_access_code = response_data['data']['access_code']
                payment.paystack_authorization_url = response_data['data']['authorization_url']
                payment.save()

                # Return the authorization URL for frontend redirect
                return Response({
                    'payment': PaymentSerializer(payment).data,
                    'authorization_url': payment.paystack_authorization_url,
                    'reference': payment.paystack_reference
                })
            else:
                payment.status = 'failed'
                payment.save()
                return Response({'error': f"Paystack error: {response_data.get('message', 'Unknown error')}"}, status=status.HTTP_400_BAD_REQUEST)

        except requests.RequestException as e:
            payment.status = 'failed'
            payment.save()
            return Response({'error': f"Network error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def verify(self, request):
        """Verify payment status with Paystack"""
        reference = request.data.get('reference')

        if not reference:
            return Response(
                {'error': 'Reference is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            payment = Payment.objects.get(
                paystack_reference=reference,
                user=request.user
            )
        except Payment.DoesNotExist:
            return Response(
                {'error': 'Payment not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # If payment is already successful, just return the investment data
        if payment.status == 'success':
            investment = payment.investment
            return Response({
                'status': 'success',
                'payment': PaymentSerializer(payment).data,
                'investment': InvestmentSerializer(investment).data
            })

        # Verify with Paystack
        paystack_secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        url = f'https://api.paystack.co/transaction/verify/{reference}'
        headers = {
            'Authorization': f'Bearer {paystack_secret_key}',
        }

        try:
            response = requests.get(url, headers=headers)
            response_data = response.json()

            if response_data.get('status') and response_data['data']['status'] == 'success':
                # Update payment status
                payment.status = 'success'
                payment.paid_at = timezone.now()
                payment.metadata = response_data['data']
                payment.save()

                # Update investment status to active
                investment = payment.investment
                if investment.status == 'pending':
                    investment.status = 'active'
                    investment.save()

                # Reduce available slots in the package
                package = investment.package
                if package.available_slots > 0:
                    package.available_slots -= 1
                    package.save()

                    # If slots are now full, cancel all pending investments
                    if package.available_slots == 0:
                        from .views import InvestmentViewSet
                        viewset = InvestmentViewSet()
                        viewset.cancel_pending_investments_for_package(package)

                return Response({
                    'status': 'success',
                    'payment': PaymentSerializer(payment).data,
                    'investment': InvestmentSerializer(investment).data
                })
            else:
                payment.status = 'failed'
                payment.save()

                return Response({
                    'status': 'failed',
                    'payment': PaymentSerializer(payment).data,
                    'message': response_data.get('message', 'Payment verification failed')
                })

        except requests.RequestException as e:
            return Response(
                {'error': f'Verification failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class PaystackWebhookView(APIView):
    """Handle Paystack webhooks"""

    permission_classes = [AllowAny]  # Webhooks don't require authentication

    def post(self, request):
        """Process Paystack webhook"""
        # Get Paystack signature for verification
        paystack_signature = request.headers.get('x-paystack-signature')
        paystack_secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', '')

        if not paystack_signature or not paystack_secret_key:
            return Response(
                {'error': 'Invalid webhook signature'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify webhook signature (simplified - in production, implement proper HMAC verification)
        import hmac
        import hashlib

        payload = request.body
        expected_signature = hmac.new(
            paystack_secret_key.encode(),
            payload,
            hashlib.sha512
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, paystack_signature):
            return Response(
                {'error': 'Invalid signature'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Process webhook data
        event = request.data.get('event')
        data = request.data.get('data', {})

        if event == 'charge.success':
            reference = data.get('reference')

            try:
                payment = Payment.objects.get(paystack_reference=reference)

                # Update payment status
                payment.status = 'success'
                payment.paid_at = timezone.now()
                payment.metadata = data
                payment.save()

                # Update investment status
                investment = payment.investment
                if investment.status == 'pending':
                    investment.status = 'active'
                    investment.save()

                    # Reduce available slots in the package
                    package = investment.package
                    if package.available_slots > 0:
                        package.available_slots -= 1
                        package.save()

                        # If slots are now full, cancel all pending investments
                        if package.available_slots == 0:
                            # Create an instance of InvestmentViewSet to access the helper method
                            from .views import InvestmentViewSet
                            viewset = InvestmentViewSet()
                            viewset.cancel_pending_investments_for_package(package)

                # Create transaction record
                Transaction.objects.create(
                    user=payment.user,
                    investment=investment,
                    transaction_type='investment',
                    amount=payment.amount,
                    status='completed',
                    payment_method='paystack',
                    payment_reference=reference,
                    description=f'Investment in {investment.package.name}'
                )

            except Payment.DoesNotExist:
                # Log error but don't fail webhook
                pass

        return Response({'status': 'success'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_status(request, investment_id):
    try:
        # Get investment and verify ownership
        investment = Investment.objects.get(
            id=investment_id,
            user=request.user
        )

        # Get most recent payment for this investment
        payment = Payment.objects.filter(
            investment=investment
        ).order_by('-created_at').first()

        response_data = {
            'investment_status': investment.status,
            'payment_exists': payment is not None,
            'can_withdraw': investment.status == 'completed' and payment and payment.status == 'success',
        }

        if payment:
            response_data.update({
                'payment_status': payment.status,
                'payment_amount': payment.amount,
                'payment_date': payment.paid_at,
            })

        return Response(response_data)

    except Investment.DoesNotExist:
        return Response(
            {'error': 'Investment not found or access denied'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# Additional utility views
from rest_framework.views import APIView

class DashboardStatsView(APIView):
    """Get dashboard statistics for authenticated user"""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Get user's investments
        investments = Investment.objects.filter(user=user)
        active_investments = investments.filter(status='active')
        completed_investments = investments.filter(status='completed')
        
        # Calculate totals
        total_invested = investments.aggregate(total=Sum('amount'))['total'] or 0
        total_returns = completed_investments.aggregate(
            total=Sum('actual_return')
        )['total'] or 0
        
        # Get recent transactions
        recent_transactions = Transaction.objects.filter(
            user=user
        ).order_by('-created_at')[:5]
        
        # Get referral earnings
        referral_earnings = Transaction.objects.filter(
            user=user,
            transaction_type='referral_bonus',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_portfolio': total_invested + total_returns,
            'active_investments': active_investments.count(),
            'monthly_returns': total_returns,  # Simplified
            'referral_earnings': referral_earnings,
            'recent_transactions': TransactionSerializer(
                recent_transactions, many=True
            ).data,
        })

class AdminUserViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin ViewSet for managing users"""
    
    permission_classes = [IsAdminUser]
    serializer_class = UserInvestmentSummarySerializer
    
    def get_queryset(self):
        return get_user_model().objects.all()
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get user statistics"""
        total_users = get_user_model().objects.count()
        active_users = get_user_model().objects.filter(is_active=True).count()
        verified_users = get_user_model().objects.filter(is_verified=True).count()
        
        return Response({
            'total_users': total_users,
            'active_users': active_users,
            'verified_users': verified_users,
        })

class AdminInvestmentViewSet(viewsets.ModelViewSet):
    """Admin ViewSet for managing all investments"""

    permission_classes = [IsAdminUser]
    serializer_class = InvestmentSerializer
    queryset = Investment.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return AdminInvestmentCreateSerializer
        return InvestmentSerializer

    def update(self, request, *args, **kwargs):
        print("=== AdminInvestmentViewSet.update called ===")
        print(f"Request data: {request.data}")
        print(f"Investment ID: {kwargs.get('pk')}")

        instance = self.get_object()
        print(f"Current investment status: {instance.status}")
        print(f"Current actual_return: {instance.actual_return}")

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        print(f"Serializer initial data: {serializer.initial_data}")

        try:
            is_valid = serializer.is_valid()
            print(f"Serializer is_valid: {is_valid}")
            if not is_valid:
                print(f"Serializer errors: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            print("About to save serializer...")
            self.perform_update(serializer)
            print("Serializer saved successfully")

            updated_instance = serializer.instance
            print(f"Updated investment status: {updated_instance.status}")
            print(f"Updated actual_return: {updated_instance.actual_return}")

            return Response(serializer.data)

        except Exception as e:
            print(f"Exception during update: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve an investment - only if payment is completed"""
        investment = self.get_object()
        
        if investment.status != 'pending':
            return Response(
                {'error': 'Only pending investments can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if there's a successful payment for this investment
        try:
            payment = Payment.objects.get(investment=investment, status='success')
        except Payment.DoesNotExist:
            return Response(
                {'error': 'Investment cannot be approved without successful payment'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if payment is actually successful
        if payment.status != 'success':
            return Response(
                {'error': 'Payment must be completed before investment can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        investment.status = 'active'
        investment.save()

        # Reduce available slots in the package
        package = investment.package
        if package.available_slots > 0:
            package.available_slots -= 1
            package.save()

            # If slots are now full, cancel all pending investments
            if package.available_slots == 0:
                from .views import InvestmentViewSet
                viewset = InvestmentViewSet()
                viewset.cancel_pending_investments_for_package(package)

        return Response({'message': 'Investment approved successfully'})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject an investment"""
        investment = self.get_object()
        
        if investment.status != 'pending':
            return Response(
                {'error': 'Only pending investments can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        investment.status = 'cancelled'
        investment.save()
        
        return Response({'message': 'Investment rejected successfully'})
    
    @action(detail=True, methods=['get'])
    def payment_status(self, request, pk=None):
        """Get payment status for an investment"""
        investment = self.get_object()
        
        try:
            payment = Payment.objects.get(investment=investment)
            return Response({
                'payment_status': payment.status,
                'payment_amount': payment.amount,
                'payment_date': payment.created_at,
                'can_approve': payment.status == 'success'
            })
        except Payment.DoesNotExist:
            return Response({
                'payment_status': 'no_payment',
                'can_approve': False
            })
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get investment statistics"""
        total_investments = Investment.objects.count()
        pending_investments = Investment.objects.filter(status='pending').count()
        active_investments = Investment.objects.filter(status='active').count()
        completed_investments = Investment.objects.filter(status='completed').count()
        total_amount = Investment.objects.aggregate(total=Sum('amount'))['total'] or 0
        
        # Count pending investments with successful payments
        pending_with_payment = 0
        for investment in Investment.objects.filter(status='pending'):
            try:
                payment = Payment.objects.get(investment=investment, status='success')
                pending_with_payment += 1
            except Payment.DoesNotExist:
                pass
        
        return Response({
            'total_investments': total_investments,
            'pending_investments': pending_investments,
            'pending_with_payment': pending_with_payment,
            'active_investments': active_investments,
            'completed_investments': completed_investments,
            'total_amount': total_amount,
        })
    
    @action(detail=True, methods=['post'])
    def force_approve(self, request, pk=None):
        """Admin-only action to force approve an investment"""
        try:
            investment = Investment.objects.get(pk=pk)
            
            # Update investment status
            investment.status = 'active'
            investment.start_date = timezone.now().date()
            investment.end_date = investment.package.end_date
            investment.save()

            # Reduce available slots in the package
            package = investment.package
            if package.available_slots > 0:
                package.available_slots -= 1
                package.save()

                # If slots are now full, cancel all pending investments
                if package.available_slots == 0:
                    from .views import InvestmentViewSet
                    viewset = InvestmentViewSet()
                    viewset.cancel_pending_investments_for_package(package)

            # Create a payment record
            Payment.objects.create(
                user=investment.user,
                investment=investment,
                amount=investment.amount,
                status='success',
                payment_method='admin_override',
                paystack_reference=f'ADMIN-APPROVAL-{timezone.now().timestamp()}',
                # These fields are required in your model
                currency='NGN',
                paystack_access_code='ADMIN-OVERRIDE',
                paystack_authorization_url='',  # Empty since this is admin override
                metadata={
                    'admin_override': True,
                    'admin_user': request.user.id
                }
            )
            
            return Response({
                'success': True,
                'message': 'Investment force approved',
                'investment': InvestmentSerializer(investment).data
            }, status=status.HTTP_200_OK)
            
        except Investment.DoesNotExist:
            return Response(
                {'error': 'Investment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['delete'])
    def hard_delete(self, request, pk=None):
        """Permanently delete an investment (admin only)"""
        try:
            investment = Investment.objects.get(pk=pk)
            investment_id = investment.id
            investment.delete()
            
            return Response({
                'success': True,
                'message': f'Investment {investment_id} permanently deleted'
            }, status=status.HTTP_200_OK)
            
        except Investment.DoesNotExist:
            return Response(
                {'error': 'Investment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def get_queryset(self):
        queryset = super().get_queryset()
        # Add any filtering logic here
        return queryset.select_related('withdrawal_request', 'user', 'package')

class AdminPackageViewSet(viewsets.ModelViewSet):
    """Admin ViewSet for managing investment packages"""

    permission_classes = [IsAdminUser]
    serializer_class = InvestmentPackageSerializer
    queryset = InvestmentPackage.objects.all()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return InvestmentPackageSerializer
        return InvestmentPackageDetailSerializer

    def create(self, request, *args, **kwargs):
        print("=== AdminPackageViewSet.create called ===")
        print(f"Request data: {request.data}")
        print(f"Request user: {request.user}")
        print(f"Request user is_staff: {request.user.is_staff}")

        serializer = self.get_serializer(data=request.data)
        print(f"Serializer initial data: {serializer.initial_data}")

        try:
            is_valid = serializer.is_valid()
            print(f"Serializer is_valid: {is_valid}")
            if not is_valid:
                print(f"Serializer errors: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            print("About to save serializer...")
            self.perform_create(serializer)
            print("Serializer saved successfully")

            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        except Exception as e:
            print(f"Exception during create: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get package statistics"""
        total_packages = InvestmentPackage.objects.count()
        active_packages = InvestmentPackage.objects.filter(status='active').count()
        total_slots = InvestmentPackage.objects.aggregate(total=Sum('total_slots'))['total'] or 0
        available_slots = InvestmentPackage.objects.aggregate(total=Sum('available_slots'))['total'] or 0
        
        return Response({
            'total_packages': total_packages,
            'active_packages': active_packages,
            'total_slots': total_slots,
            'available_slots': available_slots,
            'filled_slots': total_slots - available_slots,
        })

class AdminTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin ViewSet for viewing all transactions"""
    
    permission_classes = [IsAdminUser]
    serializer_class = TransactionSerializer
    queryset = Transaction.objects.all()
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get transaction statistics"""
        total_transactions = Transaction.objects.count()
        completed_transactions = Transaction.objects.filter(status='completed').count()
        pending_transactions = Transaction.objects.filter(status='pending').count()
        total_amount = Transaction.objects.filter(status='completed').aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        return Response({
            'total_transactions': total_transactions,
            'completed_transactions': completed_transactions,
            'pending_transactions': pending_transactions,
            'total_amount': total_amount,
        })

class AdminWithdrawalViewSet(viewsets.ModelViewSet):
    """Admin ViewSet for managing all withdrawal requests"""

    permission_classes = [IsAdminUser]
    serializer_class = WithdrawalRequestSerializer
    queryset = WithdrawalRequest.objects.all().select_related('user').prefetch_related('investments')

    def get_queryset(self):
        queryset = super().get_queryset()
        # Add any filtering logic here if needed
        return queryset.order_by('-request_date')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a withdrawal request"""
        withdrawal = self.get_object()

        if withdrawal.status != 'pending':
            return Response(
                {'error': 'Only pending withdrawals can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )

        withdrawal.status = 'approved'
        withdrawal.processed_date = timezone.now()
        withdrawal.save()

        return Response({'message': 'Withdrawal approved successfully'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a withdrawal request"""
        withdrawal = self.get_object()

        if withdrawal.status != 'pending':
            return Response(
                {'error': 'Only pending withdrawals can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )

        withdrawal.status = 'rejected'
        withdrawal.processed_date = timezone.now()
        withdrawal.admin_notes = request.data.get('notes', '')
        withdrawal.save()

        return Response({'message': 'Withdrawal rejected successfully'})

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark an approved withdrawal as paid"""
        withdrawal = self.get_object()

        if withdrawal.status != 'approved':
            return Response(
                {'error': 'Only approved withdrawals can be marked as paid'},
                status=status.HTTP_400_BAD_REQUEST
            )

        withdrawal.status = 'completed'
        withdrawal.processed_date = timezone.now()
        withdrawal.admin_notes = (withdrawal.admin_notes or '') + "\nMarked as paid manually by admin."
        withdrawal.save()

        return Response({'message': 'Withdrawal marked as paid successfully'})

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get withdrawal statistics"""
        total_withdrawals = WithdrawalRequest.objects.count()
        pending_withdrawals = WithdrawalRequest.objects.filter(status='pending').count()
        approved_withdrawals = WithdrawalRequest.objects.filter(status='approved').count()
        completed_withdrawals = WithdrawalRequest.objects.filter(status='completed').count()
        rejected_withdrawals = WithdrawalRequest.objects.filter(status='rejected').count()
        total_amount = WithdrawalRequest.objects.filter(status__in=['approved', 'completed']).aggregate(
            total=Sum('amount')
        )['total'] or 0

        return Response({
            'total_withdrawals': total_withdrawals,
            'pending_withdrawals': pending_withdrawals,
            'approved_withdrawals': approved_withdrawals,
            'completed_withdrawals': completed_withdrawals,
            'rejected_withdrawals': rejected_withdrawals,
            'total_amount': total_amount,
        })

class AdminDashboardView(APIView):
    """Admin dashboard overview with investment management actions"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        # Get all statistics
        users = get_user_model().objects
        investments = Investment.objects
        packages = InvestmentPackage.objects
        transactions = Transaction.objects

        # User stats
        total_users = users.count()
        active_users = users.filter(is_active=True).count()

        # Investment stats
        total_investments = investments.count()
        total_invested = investments.aggregate(total=Sum('amount'))['total'] or 0
        pending_investments = investments.filter(status='active').count()

        # Package stats
        total_packages = packages.count()
        active_packages = packages.filter(status='active').count()

        # Transaction stats
        total_transactions = transactions.count()
        completed_transactions = transactions.filter(status='completed').count()

        # Recent activity
        recent_investments = investments.order_by('-investment_date')[:5]
        recent_users = users.order_by('-date_joined')[:5]

        # Revenue data for chart (last 6 months)
        revenue_data = []
        for i in range(5, -1, -1):  # Last 6 months, from oldest to newest
            month_date = timezone.now().date() - timedelta(days=30*i)
            month_start = month_date.replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            month_transactions = transactions.filter(
                status='completed',
                created_at__date__gte=month_start,
                created_at__date__lte=month_end
            )

            month_revenue = month_transactions.aggregate(
                total=Sum('amount')
            )['total'] or 0

            revenue_data.append({
                'date': month_start.strftime('%Y-%m'),
                'revenue': float(month_revenue)
            })

        return Response({
            'overview': {
                'total_users': total_users,
                'active_users': active_users,
                'total_investments': total_investments,
                'total_invested': total_invested,
                'pending_investments': pending_investments,
                'total_packages': total_packages,
                'active_packages': active_packages,
                'total_transactions': total_transactions,
                'completed_transactions': completed_transactions,
            },
            'revenueData': revenue_data,
            'recent_investments': InvestmentSerializer(recent_investments, many=True).data,
            'recent_users': UserInvestmentSummarySerializer(recent_users, many=True).data,
        })





class WithdrawalRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawalRequestSerializer
    
    def get_queryset(self):
        return WithdrawalRequest.objects.filter(user=self.request.user)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CreateWithdrawalRequestSerializer
        return WithdrawalRequestSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        completed_investments = Investment.objects.filter(
            user=user,
            status='completed',
            withdrawal_request__isnull=True
        )
        
        if not completed_investments.exists():
            return Response(
                {'error': 'No completed investments available for withdrawal'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        withdrawal_type = serializer.validated_data['type']
        investment_ids = serializer.validated_data.get('investment_ids', [])
        
        if investment_ids:
            investments = completed_investments.filter(id__in=investment_ids)
        else:
            investments = completed_investments
        
        if not investments.exists():
            return Response(
                {'error': 'No valid investments selected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        total_amount = sum(inv.actual_return for inv in investments)
        principal_amount = sum(inv.amount for inv in investments)
        
        if withdrawal_type == 'interest':
            amount = total_amount - principal_amount
        elif withdrawal_type == 'reinvest':
            amount = total_amount - principal_amount
        else:  # full
            amount = total_amount
        
        # Create withdrawal first
        withdrawal = WithdrawalRequest.objects.create(
            user=user,
            amount=amount,
            type=withdrawal_type,
            status='pending'
        )
        
        # Update each investment to link to this withdrawal
        investments.update(withdrawal_request=withdrawal)
        
        # Set the many-to-many relationship
        withdrawal.investments.set(investments)
        
        output_serializer = WithdrawalRequestSerializer(withdrawal, context={'request': request})
        headers = self.get_success_headers(output_serializer.data)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED, headers=headers)







@api_view(['POST'])
@permission_classes([IsAdminUser])
def process_withdrawal(request, withdrawal_id, action):
    try:
        withdrawal = WithdrawalRequest.objects.select_for_update().get(id=withdrawal_id)
        
        if action not in ['approve', 'reject', 'mark_paid']:
            return Response(
                {'error': 'Invalid action. Use "approve", "reject", or "mark_paid".'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # MARK AS PAID
        if action == 'mark_paid':
            if withdrawal.status != 'approved':
                return Response(
                    {'error': 'Only approved withdrawals can be marked as paid.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            withdrawal.status = 'completed'
            withdrawal.processed_date = timezone.now()
            withdrawal.admin_notes = (withdrawal.admin_notes or '') + "\nMarked as paid manually by admin."
            withdrawal.save()
            return Response(
                WithdrawalRequestSerializer(withdrawal).data,
                status=status.HTTP_200_OK
            )

        # APPROVE
        if action == 'approve':
            if withdrawal.status != 'pending' and withdrawal.status != 'failed':
                return Response(
                    {'error': f'Withdrawal is already {withdrawal.status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            withdrawal.status = 'approved'
            withdrawal.processed_date = timezone.now()
            withdrawal.payment_reference = f"PAY-{int(timezone.now().timestamp())}"

        # REJECT
        elif action == 'reject':
            if withdrawal.status != 'pending':
                return Response(
                    {'error': f'Withdrawal is already {withdrawal.status}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            withdrawal.status = 'rejected'
            withdrawal.processed_date = timezone.now()
            withdrawal.admin_notes = (withdrawal.admin_notes or '') + "\nRejected by admin."

        withdrawal.save()
        return Response(
            WithdrawalRequestSerializer(withdrawal).data,
            status=status.HTTP_200_OK
        )

    except WithdrawalRequest.DoesNotExist:
        return Response(
            {'error': 'Withdrawal request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': f'Internal server error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAdminUser])
def update_withdrawal_notes(request, withdrawal_id):
    try:
        withdrawal = WithdrawalRequest.objects.get(id=withdrawal_id)
        notes = request.data.get('notes', '').strip()
        
        if not notes:
            return Response(
                {'error': 'Notes cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        withdrawal.admin_notes = notes
        withdrawal.save()
        
        return Response(
            WithdrawalRequestSerializer(withdrawal).data,
            status=status.HTTP_200_OK
        )
        
    except WithdrawalRequest.DoesNotExist:
        return Response(
            {'error': 'Withdrawal request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

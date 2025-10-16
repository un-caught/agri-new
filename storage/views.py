from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from django.shortcuts import get_object_or_404
from django.db.models import Sum, Avg, Count, Q
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from datetime import date, datetime
import uuid
import hashlib
import hmac

from .models import StoragePlan, StorageInvestment, PaymentTransaction, StorageUpdate
from .serilizers import (
    StoragePlanSerializer, InvestmentSerializer, InvestmentCreateSerializer,
    PaymentTransactionSerializer, DashboardStatsSerializer
)
from .services.payment_service import PaymentService


class StoragePlanListView(generics.ListCreateAPIView):
    """List all available storage plans"""
    serializer_class = StoragePlanSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        """
        GET requests require only authentication
        POST requests require admin privileges
        """
        if self.request.method == 'POST':
            return [IsAdminUser()]
        return [IsAuthenticated()]


    def get_queryset(self):
        user = self.request.user

        # If admin → show all storage plans
        if user.is_staff or user.is_superuser:
            queryset = StoragePlan.objects.all()
        else:
            # Regular users → only active ones
            queryset = StoragePlan.objects.filter(is_active=True)
        
        # Filter by product name
        product_name = self.request.query_params.get('product_name')
        if product_name:
            queryset = queryset.filter(product_name__icontains=product_name)
        
        # Filter by minimum ROI
        min_roi = self.request.query_params.get('min_roi')
        if min_roi:
            # This would require a custom filter since roi_percentage is a property
            pass
        
        # Filter by availability (only for non-admin users)
        if not (user.is_staff or user.is_superuser):
            available_only = self.request.query_params.get('available_only', 'true')
            if available_only.lower() == 'true':
                queryset = queryset.filter(available_quantity__gt=0)
        
        return queryset.order_by('-created_at')

    def create(self, request, *args, **kwargs):
        """Override create to add debugging prints"""
        print("DEBUG: StoragePlanListView.create - Starting POST request")
        print("DEBUG: Request method:", request.method)
        print("DEBUG: Request user:", request.user)
        print("DEBUG: User is admin:", request.user.is_staff if request.user.is_authenticated else False)
        print("DEBUG: Request data keys:", list(request.data.keys()))
        print("DEBUG: Request content type:", request.content_type)

        # Handle multipart form data - convert lists to single values
        cleaned_data = {}
        for key, value in request.data.items():
            if isinstance(value, list) and len(value) == 1:
                cleaned_data[key] = value[0]
            else:
                cleaned_data[key] = value

        print("DEBUG: Cleaned request data:", cleaned_data)

        serializer = self.get_serializer(data=cleaned_data)
        print("DEBUG: Serializer created with data")

        is_valid = serializer.is_valid()
        print("DEBUG: Serializer is_valid():", is_valid)

        if not is_valid:
            print("DEBUG: Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        print("DEBUG: Validated data:", serializer.validated_data)

        try:
            self.perform_create(serializer)
            print("DEBUG: perform_create completed successfully")
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as e:
            print("DEBUG: Exception in create:", str(e))
            import traceback
            print("DEBUG: Full traceback:", traceback.format_exc())
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_create(self, serializer):
        """Save the new storage plan"""
        serializer.save()


class StoragePlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get detailed information about a specific storage plan"""
    queryset = StoragePlan.objects.all()
    serializer_class = StoragePlanSerializer

    def get_permissions(self):
        if self.request.method in ['PATCH', 'PUT', 'DELETE']:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def update(self, request, *args, **kwargs):
        print("DEBUG: Starting StoragePlanDetailView.update")
        print("DEBUG: Request method:", request.method)
        print("DEBUG: Request user:", request.user)
        print("DEBUG: User is admin:", request.user.is_staff or request.user.is_superuser)
        print("DEBUG: Request data:", request.data)
        print("DEBUG: Request headers:", dict(request.headers))

        instance = self.get_object()
        print("DEBUG: Instance before update:", instance.__dict__)

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        print("DEBUG: Serializer created")

        is_valid = serializer.is_valid()
        print("DEBUG: Serializer is_valid():", is_valid)

        if not is_valid:
            print("DEBUG: Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        print("DEBUG: Validated data:", serializer.validated_data)

        try:
            response = super().update(request, *args, **kwargs)
            print("DEBUG: Update successful, response data:", response.data)
            return response
        except Exception as e:
            print("DEBUG: Exception during update:", str(e))
            print("DEBUG: Exception type:", type(e))
            import traceback
            print("DEBUG: Full traceback:", traceback.format_exc())
            raise

    def destroy(self, request, *args, **kwargs):
        """Override destroy to add debugging and check for related investments"""
        print("DEBUG: Starting StoragePlanDetailView.destroy")
        print("DEBUG: Request method:", request.method)
        print("DEBUG: Request user:", request.user)
        print("DEBUG: User is admin:", request.user.is_staff or request.user.is_superuser)

        instance = self.get_object()
        print("DEBUG: Instance to delete:", instance.__dict__)

        # Check if there are any related investments
        related_investments = StorageInvestment.objects.filter(storage_plan=instance)
        if related_investments.exists():
            print("DEBUG: Found related investments, count:", related_investments.count())
            return Response({
                'error': 'Cannot delete storage plan with existing investments. Please delete all related investments first.'
            }, status=status.HTTP_400_BAD_REQUEST)

        print("DEBUG: No related investments found, proceeding with deletion")

        try:
            response = super().destroy(request, *args, **kwargs)
            print("DEBUG: Deletion successful")
            return response
        except Exception as e:
            print("DEBUG: Exception during deletion:", str(e))
            import traceback
            print("DEBUG: Full traceback:", traceback.format_exc())
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def purchase_storage_plan(request):
    """Purchase a storage plan and initiate payment"""
    serializer = InvestmentCreateSerializer(data=request.data, context={'request': request})
    
    if serializer.is_valid():
        try:
            # Create investment
            investment = serializer.save()
            
            # Create payment transaction
            payment_service = PaymentService()
            payment_transaction = payment_service.create_payment(investment)
            
            # Return response with payment URL
            return Response({
                'success': True,
                'message': 'Investment created successfully',
                'investment_id': investment.id,
                'payment_url': payment_transaction.payment_url,
                'payment_reference': payment_transaction.reference,
                'amount': float(payment_transaction.amount)
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Failed to create investment: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    return Response({
        'success': False,
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


class MyInvestmentsView(generics.ListAPIView):
    """List current user's investments"""
    serializer_class = InvestmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = StorageInvestment.objects.filter(user=self.request.user)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at')


class AdminStorageInvestmentsView(generics.ListCreateAPIView):
    """List and create storage investments for admin"""
    serializer_class = InvestmentSerializer
    permission_classes = [IsAdminUser]
    queryset = StorageInvestment.objects.all().order_by('-created_at')

    def create(self, request, *args, **kwargs):
        """Override create to add debugging prints"""
        print("DEBUG: AdminStorageInvestmentsView.create - Starting POST request")
        print("DEBUG: Request method:", request.method)
        print("DEBUG: Request user:", request.user)
        print("DEBUG: User is admin:", request.user.is_staff if request.user.is_authenticated else False)
        print("DEBUG: Request data keys:", list(request.data.keys()))
        print("DEBUG: Request content type:", request.content_type)
        print("DEBUG: Full request data:", request.data)

        # Handle multipart form data - convert lists to single values
        cleaned_data = {}
        for key, value in request.data.items():
            if isinstance(value, list) and len(value) == 1:
                cleaned_data[key] = value[0]
            else:
                cleaned_data[key] = value

        print("DEBUG: Cleaned request data:", cleaned_data)

        # Check if this is admin creation (different from user creation)
        if 'user_email' in cleaned_data:
            print("DEBUG: Admin creation detected - need to transform data")
            # This is admin creation, transform the data to match InvestmentCreateSerializer
            try:
                from users.models import User
                user = User.objects.get(email=cleaned_data['user_email'])
                print("DEBUG: Found user:", user.email, "ID:", user.id)

                # Transform admin form data to serializer expected format
                # Admin form sends quantity in tons, but serializer expects quantity in bags
                # Need to check what unit the admin form is using vs what the plan expects
                quantity_tons = float(cleaned_data['quantity'])
                print("DEBUG: Quantity from admin form (tons):", quantity_tons)

                # Get the storage plan to understand the units
                from .models import StoragePlan
                try:
                    storage_plan = StoragePlan.objects.get(id=cleaned_data['storage_plan'])
                    print("DEBUG: Storage plan max quantity:", storage_plan.maximum_quantity)
                    print("DEBUG: Storage plan available quantity:", storage_plan.available_quantity)
                except StoragePlan.DoesNotExist:
                    print("DEBUG: Storage plan not found")
                    return Response({'error': 'Storage plan not found'}, status=status.HTTP_400_BAD_REQUEST)

                # Admin form sends quantity directly in bags (not tons)
                quantity_bags = int(float(quantity_tons))
                print("DEBUG: Using quantity directly as bags:", quantity_tons, "->", quantity_bags, "bags")

                # Get status from request or default to 'active' for admin-created investments
                status_value = cleaned_data.get('status', 'active')
                print("DEBUG: Status from request:", status_value)

                transformed_data = {
                    'plan_id': cleaned_data['storage_plan'],
                    'quantity_bags': quantity_bags,
                    'customer_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                    'customer_email': user.email,
                    'customer_phone': getattr(user, 'phone', '') or '',
                    'status': status_value
                }
                print("DEBUG: Final transformed data for serializer:", transformed_data)
                print("DEBUG: Transformed data for serializer:", transformed_data)

                serializer = InvestmentCreateSerializer(data=transformed_data, context={'request': request})
                print("DEBUG: Using InvestmentCreateSerializer for admin creation")

            except User.DoesNotExist:
                print("DEBUG: User not found with email:", cleaned_data.get('user_email'))
                return Response({'error': 'User not found'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                print("DEBUG: Error transforming admin data:", str(e))
                return Response({'error': f'Data transformation error: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            print("DEBUG: Regular creation - using InvestmentSerializer")
            serializer = self.get_serializer(data=cleaned_data)

        print("DEBUG: Serializer created with data")

        is_valid = serializer.is_valid()
        print("DEBUG: Serializer is_valid():", is_valid)

        if not is_valid:
            print("DEBUG: Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        print("DEBUG: Validated data:", serializer.validated_data)

        try:
            instance = serializer.save()
            print("DEBUG: Instance created successfully:", instance.id)

            # Use the view's default serializer for the response
            response_serializer = self.get_serializer(instance)
            print("DEBUG: Response serializer created")

            headers = self.get_success_headers(response_serializer.data)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as e:
            print("DEBUG: Exception in create:", str(e))
            import traceback
            print("DEBUG: Full traceback:", traceback.format_exc())
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminStorageInvestmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, and delete storage investment for admin"""
    serializer_class = InvestmentSerializer
    permission_classes = [IsAdminUser]
    queryset = StorageInvestment.objects.all()


class InvestmentDetailView(generics.RetrieveAPIView):
    """Get detailed information about a specific investment"""
    serializer_class = InvestmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StorageInvestment.objects.filter(user=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """Get dashboard statistics for the current user"""
    user_investments = StorageInvestment.objects.filter(user=request.user)
    
    # Calculate statistics
    stats = {
        'total_investments': user_investments.count(),
        'total_invested_amount': user_investments.aggregate(
            total=Sum('total_investment_amount')
        )['total'] or 0,
        'total_projected_returns': user_investments.aggregate(
            total=Sum('projected_returns')
        )['total'] or 0,
        'active_investments': user_investments.filter(status='active').count(),
        'pending_investments': user_investments.filter(status='pending').count(),
        'matured_investments': user_investments.filter(status='matured').count(),
        'completed_investments': user_investments.filter(status='completed').count(),
    }
    
    # Calculate average ROI
    if stats['total_invested_amount'] > 0:
        stats['average_roi'] = round(
            ((stats['total_projected_returns'] - stats['total_invested_amount']) 
             / stats['total_invested_amount']) * 100, 2
        )
    else:
        stats['average_roi'] = 0
    
    serializer = DashboardStatsSerializer(stats)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([AllowAny])
def paystack_webhook(request):
    """Handle Paystack webhook for payment verification"""
    import json
    from django.conf import settings
    
    # Verify webhook signature
    signature = request.headers.get('x-paystack-signature')
    if not signature:
        return Response({'error': 'No signature'}, status=400)
    
    payload = request.body
    computed_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    
    if signature != computed_signature:
        return Response({'error': 'Invalid signature'}, status=400)
    
    try:
        data = json.loads(payload)
        event = data.get('event')
        
        if event == 'charge.success':
            reference = data['data']['reference']
            
            try:
                payment_transaction = PaymentTransaction.objects.get(reference=reference)
                investment = payment_transaction.investment
                
                # Update payment status
                payment_transaction.status = 'successful'
                payment_transaction.gateway_reference = data['data']['id']
                payment_transaction.paid_at = datetime.now()
                payment_transaction.save()
                
                # Update investment status
                investment.status = 'active'
                investment.payment_status = 'paid'
                investment.payment_date = datetime.now()
                investment.payment_reference = reference
                investment.save()
                
                # Create storage update
                StorageUpdate.objects.create(
                    investment=investment,
                    update_type='storage_start',
                    title='Payment Confirmed - Storage Started',
                    message=f'Your payment of ₦{payment_transaction.amount:,.2f} has been confirmed. Your {investment.product_name} storage has officially started.'
                )
                
                return Response({'status': 'success'})
                
            except PaymentTransaction.DoesNotExist:
                return Response({'error': 'Transaction not found'}, status=404)
        
        elif event == 'charge.failed':
            reference = data['data']['reference']
            
            try:
                payment_transaction = PaymentTransaction.objects.get(reference=reference)
                investment = payment_transaction.investment
                
                # Update payment status
                payment_transaction.status = 'failed'
                payment_transaction.save()
                
                # Release reserved quantity
                investment.storage_plan.release_quantity(investment.quantity_bags)
                
                # Update investment status
                investment.status = 'cancelled'
                investment.save()
                
                return Response({'status': 'success'})
                
            except PaymentTransaction.DoesNotExist:
                return Response({'error': 'Transaction not found'}, status=404)
    
    except Exception as e:
        return Response({'error': str(e)}, status=500)
    
    return Response({'status': 'success'})


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def verify_payment(request):
    """Manually verify payment status"""
    reference = request.data.get('reference')

    if not reference:
        return Response({'error': 'Reference is required'}, status=400)

    try:
        payment_transaction = PaymentTransaction.objects.get(reference=reference)
        investment = payment_transaction.investment

        # If payment is already successful, just return the investment data
        if payment_transaction.status == 'successful' and investment.status == 'active':
            return Response({
                'success': True,
                'message': 'Payment already verified',
                'investment': InvestmentSerializer(investment).data,
                'redirect_url': f'/payment-success?reference={reference}&status=success'
            })

        payment_service = PaymentService()

        # Verify with payment gateway
        verification_result = payment_service.verify_payment(reference)

        if verification_result['status'] == 'success':
            # Update payment and investment status
            payment_transaction.status = 'successful'
            payment_transaction.paid_at = datetime.now()
            payment_transaction.save()

            investment.status = 'active'
            investment.payment_status = 'paid'
            investment.payment_date = datetime.now()
            investment.save()

            # Create success notification/update
            StorageUpdate.objects.create(
                investment=investment,
                update_type='storage_start',
                title='Payment Confirmed - Storage Started',
                message=f'Your payment of ₦{payment_transaction.amount:,.2f} has been confirmed. Your {investment.product_name} storage has officially started.'
            )

            return Response({
                'success': True,
                'message': 'Payment verified successfully',
                'investment': InvestmentSerializer(investment).data,
                'redirect_url': f'/payment-success?reference={reference}&status=success'
            })
        else:
            return Response({
                'success': False,
                'message': 'Payment verification failed',
                'redirect_url': f'/payment-success?reference={reference}&status=failed'
            })

    except PaymentTransaction.DoesNotExist:
        return Response({'error': 'Transaction not found', 'redirect_url': '/payment-success?status=not_found'}, status=404)
    except Exception as e:
        return Response({'error': str(e), 'redirect_url': '/payment-success?status=error'}, status=500)


# Authentication Views
@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """Register a new user"""
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')
    
    if not all([username, email, password]):
        return Response({
            'error': 'Username, email, and password are required'
        }, status=400)
    
    if User.objects.filter(username=username).exists():
        return Response({'error': 'Username already exists'}, status=400)
    
    if User.objects.filter(email=email).exists():
        return Response({'error': 'Email already exists'}, status=400)
    
    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        return Response({
            'success': True,
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
        }, status=201)
    
    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """Login user and return token"""
    username = request.data.get('username')
    password = request.data.get('password')
    
    if not all([username, password]):
        return Response({
            'error': 'Username and password are required'
        }, status=400)
    
    user = authenticate(username=username, password=password)
    
    if user:
        # Create or get token (you'll need to install djangorestframework-authtoken)
        from rest_framework.authtoken.models import Token
        token, created = Token.objects.get_or_create(user=user)
        
        return Response({
            'success': True,
            'token': token.key,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
        })
    else:
        return Response({
            'error': 'Invalid credentials'
        }, status=401)
    
# storage/views.py
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mature_investment(request, investment_id):
    try:
        investment = StorageInvestment.objects.get(
            id=investment_id,
            user=request.user
        )
        
        # Validate investment can be matured
        if investment.status == 'matured':
            return Response({
                'success': False,
                'message': 'Investment is already matured'
            }, status=400)
            
        if investment.status != 'active':
            return Response({
                'success': False,
                'message': 'Only active investments can be matured'
            }, status=400)
            
        if date.today() < investment.due_date:
            return Response({
                'success': False,
                'message': 'Investment is not yet due for maturation'
            }, status=400)
        
        # Update investment status to matured
        investment.status = 'matured'
        investment.matured_date = datetime.now()  # Add this field to your model if needed
        investment.save()
        
        # Create maturation update
        StorageUpdate.objects.create(
            investment=investment,
            update_type='maturity',
            title='Investment Matured',
            message=f'Your {investment.storage_plan.product_name} investment has matured and is ready for sale.'
        )
        
        return Response({
            'success': True,
            'message': 'Investment marked as matured',
            'investment': InvestmentSerializer(investment).data
        })
        
    except StorageInvestment.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Investment not found'
        }, status=404)
    except Exception as e:
        return Response({
            'success': False,
            'message': str(e)
        }, status=500)
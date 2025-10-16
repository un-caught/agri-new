from rest_framework import viewsets
from .models import Product, Order, Cart, CartItem, OrderItem
from .serializers import ProductSerializer, OrderSerializer, CartSerializer, CartItemSerializer
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

import requests
import secrets
from decimal import Decimal
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import redirect



# Create your views here.

class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        # Admins see all products
        if user.is_staff or user.is_superuser:
            return Product.objects.all()
        
        # Regular users see only active ones
        return Product.objects.filter(is_active=True)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class CartViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        serializer = CartSerializer(cart)
        return Response(serializer.data)


@method_decorator(csrf_exempt, name='dispatch')
class CartItemView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Add or update item in cart"""
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

        if quantity > product.stock:
            return Response(
                {'error': f'Only {product.stock} units available in stock.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        cart, _ = Cart.objects.get_or_create(user=request.user)

        try:
            cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
            # Always set to the specified quantity (not add to it)
            cart_item.quantity = quantity
            cart_item.save()

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    def delete(self, request):
        """Remove item from cart"""
        product_id = request.data.get('product_id')
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            return Response({'detail': 'Cart not found'}, status=status.HTTP_404_NOT_FOUND)

        CartItem.objects.filter(cart=cart, product_id=product_id).delete()
        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)


class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            print("InitializePaymentView: Starting payment initialization")
            data = request.data
            print(f"Received data: {data}")
            email = data.get('email')
            amount = Decimal(str(data.get('amount', 0)))
            first_name = data.get('first_name')
            last_name = data.get('last_name')
            phone = data.get('phone', '')
            address = data.get('address')
            city = data.get('city')
            state = data.get('state')
            cart_items = data.get('cart_items', [])

            print(f"Parsed data: email={email}, amount={amount}, cart_items={len(cart_items)}")

            if not all([email, first_name, last_name, address, city, state]) or amount <= 0:
                print("Validation failed: missing required fields")
                return Response({
                    'error': 'Missing required fields: email, first_name, last_name, address, city, state are required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Generate unique reference
            reference = f"order_{secrets.token_urlsafe(10)}"
            print(f"Generated reference: {reference}")

            # Create order
            print("Creating order...")
            order = Order.objects.create(
                reference=reference,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                address=address,
                city=city,
                state=state,
                total_amount=amount,
                user=request.user if request.user.is_authenticated else None
            )
            print(f"Order created: {order.id}")

            # Create order items
            print("Creating order items...")
            for item_data in cart_items:
                try:
                    product = Product.objects.get(id=item_data['product_id'])
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=item_data['quantity'],
                        price=Decimal(str(item_data['price']))
                    )
                    print(f"Created order item for product {product.name}")
                except Product.DoesNotExist:
                    order.delete()
                    print(f"Product not found: {item_data['product_id']}")
                    return Response({
                        'error': f'Product with id {item_data["product_id"]} not found'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Initialize Paystack payment
            print("Initializing Paystack payment...")
            paystack_data = {
                'email': email,
                'amount': int(amount * 100),  # Convert to kobo
                'reference': reference,
                'currency': 'NGN',
                'callback_url': f"{settings.FRONTEND_URL}/payment-success?reference={reference}",
            }

            headers = {
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json',
            }

            print(f"Paystack data: {paystack_data}")
            response = requests.post(
                'https://api.paystack.co/transaction/initialize',
                json=paystack_data,
                headers=headers
            )
            print(f"Paystack response status: {response.status_code}")

            if response.status_code == 200:
                paystack_response = response.json()
                print(f"Paystack response: {paystack_response}")
                return Response({
                    'reference': reference,
                    'authorization_url': paystack_response['data']['authorization_url'],
                    'access_code': paystack_response['data']['access_code'],
                    'public_key': settings.PAYSTACK_PUBLIC_KEY
                })
            else:
                print(f"Paystack error: {response.text}")
                order.delete()
                return Response({
                    'error': 'Failed to initialize payment'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            print(f"Exception in InitializePaymentView: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class VerifyPaymentView(APIView):
    def post(self, request):
        try:
            reference = request.data.get('reference')
            
            if not reference:
                return Response({
                    'error': 'Reference is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Get order
            try:
                order = Order.objects.get(reference=reference)
            except Order.DoesNotExist:
                return Response({
                    'error': 'Order not found'
                }, status=status.HTTP_404_NOT_FOUND)

            # Verify payment with Paystack
            headers = {
                'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json',
            }

            response = requests.get(
                f'https://api.paystack.co/transaction/verify/{reference}',
                headers=headers
            )

            if response.status_code == 200:
                paystack_data = response.json()
                
                if paystack_data['data']['status'] == 'success':
                    # Update order status
                    order.status = 'paid'
                    order.paystack_reference = paystack_data['data']['reference']
                    order.save()

                    for item in order.items.all():
                        if item.product and item.product.stock >= item.quantity:
                            item.product.stock -= item.quantity
                            item.product.save()

                    # Clear user's cart if authenticated
                    if request.user.is_authenticated:
                        try:
                            cart = Cart.objects.get(user=request.user)
                            cart.items.all().delete()

                        except Cart.DoesNotExist:
                            pass

                    return Response({
                        'status': 'success',
                        'message': 'Payment verified successfully',
                        'order_id': order.id
                    })
                else:
                    order.status = 'cancelled'
                    order.save()
                    return Response({
                        'status': 'failed',
                        'message': 'Payment verification failed'
                    })
            else:
                return Response({
                    'error': 'Failed to verify payment'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    """Handle Paystack webhooks for additional security"""
    
    def post(self, request):
        try:
            # Verify webhook signature (recommended for production)
            signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
            
            if signature:
                import hmac
                import hashlib
                
                body = request.body
                computed_signature = hmac.new(
                    settings.PAYSTACK_SECRET_KEY.encode(),
                    body,
                    hashlib.sha512
                ).hexdigest()
                
                if signature != computed_signature:
                    return Response({'error': 'Invalid signature'}, status=400)

            data = request.data
            event = data.get('event')
            
            if event == 'charge.success':
                reference = data['data']['reference']
                try:
                    order = Order.objects.get(reference=reference)
                    order.status = 'confirmed'
                    order.save()
                except Order.DoesNotExist:
                    pass

            return Response({'status': 'success'})
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)

@method_decorator(csrf_exempt, name='dispatch')
class PaymentCallbackView(APIView):
    """Handle Paystack payment callback redirect"""

    def get(self, request):
        reference = request.GET.get("reference") or request.GET.get("trxref")

        if not reference:
            # Redirect to frontend with error
            return redirect(f"{settings.FRONTEND_URL}/payment-success?status=error&message=No reference provided")

        try:
            # Verify the payment
            headers = {
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"https://api.paystack.co/transaction/verify/{reference}",
                headers=headers
            )

            if response.status_code == 200:
                paystack_data = response.json()

                if paystack_data["data"]["status"] == "success":
                    # Update order status
                    try:
                        order = Order.objects.get(reference=reference)
                        order.status = "paid"
                        order.paystack_reference = paystack_data["data"]["reference"]
                        order.save()
                    except Order.DoesNotExist:
                        pass

                    # Redirect to frontend success page
                    return redirect(f"{settings.FRONTEND_URL}/payment-success?reference={reference}&status=success")
                else:
                    # Payment failed
                    return redirect(f"{settings.FRONTEND_URL}/payment-success?reference={reference}&status=error&message=Payment failed")
            else:
                return redirect(f"{settings.FRONTEND_URL}/payment-success?reference={reference}&status=error&message=Verification failed")

        except Exception as e:
            return redirect(f"{settings.FRONTEND_URL}/payment-success?reference={reference}&status=error&message={str(e)}")

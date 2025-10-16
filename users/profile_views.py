from asyncio.log import logger
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from investments.serializers import UserInvestmentSummarySerializer

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_profile_picture(request):
    """
    Update current user's profile picture
    """
    print("Starting profile picture update")
    user = request.user
    print(f"User: {user}")

    try:
        print("Checking for profile_picture in request.FILES")
        if 'profile_picture' not in request.FILES:
            print("No profile picture file provided")
            return Response(
                {'error': 'No profile picture file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile_picture = request.FILES['profile_picture']
        print(f"Profile picture file: {profile_picture.name}, size: {profile_picture.size}, type: {profile_picture.content_type}")

        # Validate file type
        print("Validating file type")
        allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
        if profile_picture.content_type not in allowed_types:
            print(f"Invalid content type: {profile_picture.content_type}")
            return Response(
                {'error': 'Only JPEG, PNG, and JPG files are allowed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate file size (max 5MB)
        print("Validating file size")
        max_size = 5 * 1024 * 1024  # 5MB
        if profile_picture.size > max_size:
            print(f"File size too big: {profile_picture.size}")
            return Response(
                {'error': 'File size must be less than 5MB'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update user's profile picture
        print("Updating user profile picture")
        user.profile_picture = profile_picture
        user.save()
        print("User saved successfully")

        # Return updated user data with full profile picture URL
        print("Serializing user data")
        serializer = UserInvestmentSummarySerializer(user, context={'request': request})
        print("Serialization complete")

        print("Returning success response")
        return Response({
            'success': 'Profile picture updated successfully',
            'user': serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        logger.error(f"Profile picture update error: {str(e)}", exc_info=True)
        print("Returning error response")
        return Response(
            {'error': 'An unexpected error occurred while updating profile picture'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

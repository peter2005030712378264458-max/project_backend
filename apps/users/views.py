from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import CreateAPIView
from .models import User
from .serializers import RegisterSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken



class RegisterView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer

class MeView(APIView):
    
    permission_classes = (IsAuthenticated, )

    
    def get(self, request):
        return Response({
            "email": request.user.email,
            "first_name": request.user.first_name, 
            "registered_at": request.user.date_joined,
        })

class CookieTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code != 200:
            return response

        data = response.data
        access = data.get("access")
        refresh = data.get("refresh")

        new_response = Response({"access": access})

        new_response.set_cookie(
            key="refresh_token",
            value=refresh,
            httponly=True,
            secure=False,
            samesite="Lax",   
            path="/"  
        )

        return new_response
    
class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get("refresh_token")

        if not refresh:
            return Response({"error": "No refresh token"}, status=401) # скорей всего удалить 

        print(refresh)
        print(request.data["refresh"])
        
        data = request.data.copy()   
        data["refresh"] = refresh
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get("refresh_token")

        if not refresh:
            return Response({"error": "No refresh token"}, status=401)

        data = request.data.copy()   
        data["refresh"] = refresh

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        response = Response(serializer.validated_data, status=200)

        return response

class LogoutView(APIView):
    def post(self, request):
        refresh = request.COOKIES.get("refresh_token")

        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except Exception:
                pass
            
        response = Response({"message": "Logged out"})
        response.delete_cookie("refresh_token")

        return response
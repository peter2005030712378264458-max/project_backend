from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import CreateAPIView
from .models import User
from .serializers import RegisterSerializer

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

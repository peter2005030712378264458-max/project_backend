from django.contrib import admin
from django.urls import path, include
# from apps.users import urls 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.urls')),
    path('api/consumption/', include('apps.consumption.urls')),
]

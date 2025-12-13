from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("upload/", views.upload_view, name="upload"),
]
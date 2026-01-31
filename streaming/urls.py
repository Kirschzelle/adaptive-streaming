from django.urls import path
from django.contrib.auth.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("upload/", views.upload_view, name="upload"),
    path("search/", views.search, name="search"),
    path("detailed_view/<int:id>/", views.detailed_view, name="detailed_view"),
    path("status/<str:task_id>/", views.task_status, name="task_status"),
    path("experiments/start/", views.start_emulation, name="start_emulation"),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
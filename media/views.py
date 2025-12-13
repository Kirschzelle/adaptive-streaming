from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login

def home_view(request):
    return render (request, "home.html")

def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = UserCreationForm()

    context = {
        "form": form
    }
    return render(request, "signup.html", context)

def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("home")
    else:
        form = AuthenticationForm()
        
    context = {
        "form": form
    }
    return render(request, "login.html", context)

def upload_view(request):
    if not request.user.is_authenticated:
        return redirect("home")
    
    context = {
        "form": "123"
    }
    return render(request, "upload.html", context)
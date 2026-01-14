from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login
from .forms import VideoForm
from .tasks import search_videos, run_network_emulation
from .models import Video
from django.http import JsonResponse
from celery.result import AsyncResult
from django.conf import settings
import json
from pathlib import Path

def home_view(request):
    return render (request, "home.html")

def search(request):
    query = request.GET.get("q", "")

    if not query:
        return JsonResponse({"error": "No query provided"}, status=400)

    task = search_videos.delay(query)

    return JsonResponse({
        "task_id": task.id,
        "status": "started",
        "message": f"Search started for '{query}'",
    })

def task_status(_request, task_id):
    task = AsyncResult(task_id)

    if task.ready():
        result = task.result

        results = Video.objects.filter(
            id__in=[r["id"] for r in result["results"]]
        )

        return JsonResponse({
            "status": "completed",
            "count": result["count"],
            "results": list(results.values("id", "title", "description")),
        })
    else:
        return JsonResponse({
            "status": "pending",
        })

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
    
    if request.method == "POST":
        form = VideoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("home")
    else:
        form = VideoForm()

    context = {
        "form": form
    }
    return render(request, "upload.html", context)

def detailed_view(request, id):
    video = get_object_or_404(Video, id=id)
    traces_dir = Path(settings.BASE_DIR) / "experiments" / "traces"
    trace_files = sorted([p.name for p in traces_dir.glob("*.csv")])

    context = {
        "video": video,
        "trace_files": trace_files
    }
    return render(request, "detailed_view.html", context)

def start_emulation(request):
    data = json.loads(request.body)

    task = run_network_emulation.delay(
        video_id=data["video_id"],
        traces=data.get("traces"),
        duration=data.get("duration", 60),
    )
    print(data.get("traces"))
    return JsonResponse({"task_id": task.id})
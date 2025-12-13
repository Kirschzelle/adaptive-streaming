from django.db import models
from django.core.exceptions import ValidationError
import os

def validate_video_file(value):
    ext = os.path.splitext(value.name)[1].lower()
    allowed_extensions = (".mp4", ".mov", ".avi", ".mkv", ".webm")

    if ext not in allowed_extensions:
        raise ValidationError("Only video files are allowed (mp4, mov, avi, mkv, webm).")

class Video(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    video = models.FileField(
        upload_to="videos/",
        validators=[validate_video_file]
        
    )
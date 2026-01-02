from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
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
        upload_to="videos/originals/",
        validators=[validate_video_file]
    )
    
    dash_manifest = models.FileField(
        upload_to='videos/dash/',
        blank=True,
        null=True,
    )
    
    dash_base_path = models.CharField(
        max_length=255,
        blank=True,
    )
    
    processing = models.BooleanField(default=False)
    dash_ready = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(default=timezone.now)
    duration = models.FloatField(
        null=True,
        blank=True,
    )
    
    def __str__(self):
        return self.title
    
    class Meta:
        ordering = ['-created_at']
    
    @property
    def is_streamable(self):
        """Check if video is ready for adaptive streaming"""
        return self.dash_ready and bool(self.dash_manifest)
    
    @property
    def manifest_url(self):
        """Get the URL for the DASH manifest"""
        if self.dash_manifest:
            return self.dash_manifest.url
        return None
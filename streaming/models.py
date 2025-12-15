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
    processing = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']

class Resolution(models.TextChoices):
    UHD_4K = '2160p', '4K (2160p)'
    FHD = '1080p', 'Full HD (1080p)'
    HD = '720p', 'HD (720p)'
    SD = '480p', 'SD (480p)'
    LOW = '360p', 'Low (360p)'

class VideoVariant(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='variants')
    resolution = models.CharField(max_length=20, choices=Resolution.choices)
    file = models.FileField(upload_to='videos/variants/%Y/%m/%d/')

    def __str__(self):
        return self.video.title + "_" + self.resolution
    
class CurrentEncode(models.Model):
    video_variant = models.ForeignKey(
        VideoVariant, 
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    started_at = models.DateTimeField(auto_now_add=True)
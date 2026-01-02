from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .models import Video
from .tasks import encode_video
import shutil
import os

@receiver(post_delete, sender=Video)
def delete_video_files(sender, instance, **kwargs):
    if instance.video:
        instance.video.delete(save=False)
    
    if instance.dash_manifest:
        instance.dash_manifest.delete(save=False)
    
    if instance.dash_base_path:
        storage = instance.dash_manifest.storage
        try:
            dash_full_path = os.path.join(storage.location, instance.dash_base_path)
            if os.path.exists(dash_full_path):
                shutil.rmtree(dash_full_path)
        except Exception as e:
            print(f"Error cleaning up DASH files: {e}")

@receiver(post_save, sender=Video)
def queue_video_encoding(sender, instance, created, **kwargs):
    _ = sender
    _ = kwargs
    _ = created
    
    if instance.video and not instance.processing:
        encode_video.apply_async(args=[instance.id], queue="video_encoding")
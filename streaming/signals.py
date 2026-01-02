from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .models import Video
from .tasks import encode_video

@receiver(post_delete, sender=Video)
def delete_video_file(sender, instance, **kwargs):
    _ = sender
    _ = kwargs
    
    if instance.video:
        instance.video.delete(save=False)

@receiver(post_save, sender=Video)
def queue_video_encoding(sender, instance, created, **kwargs):
    _ = sender
    _ = kwargs
    _ = created
    
    if instance.video and not instance.processing:
        encode_video.delay(instance.id, queue='video_encoding')
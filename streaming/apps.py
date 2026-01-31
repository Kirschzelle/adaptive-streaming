from django.apps import AppConfig

class StreamingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'streaming'
    
    def ready(self):
        import os
        run_requeue = os.environ.get('RUN_REQUEUE', '').lower() != 'false'
        
        if run_requeue:
            requeue_interrupted_encodes()

def requeue_interrupted_encodes():
    from .models import Video
    from .tasks import encode_video
    videos_to_encode = Video.objects.filter(
        video__isnull=False,
        processing=False,
        dash_ready=False
    ).exclude(video='')
    
    count = 0
    for video in videos_to_encode:
        encode_video.apply_async(args=[video.id], queue="video_encoding")
        count += 1
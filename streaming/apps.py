from django.apps import AppConfig

class StreamingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'streaming'
    
    def ready(self):
        import streaming.signals

        #requeue_interrupted_encodes()

#def requeue_interrupted_encodes():
#    from django.db.utils import OperationalError, ProgrammingError
#    from .models import CurrentEncode
#    from .tasks import encode_video_resolution

#    try:
#        interrupted = CurrentEncode.objects.all()

#        for encode in interrupted:
#            if encode.video_variant:
#                encode_video_resolution.delay(
#                    encode.video_variant.video.id,
#                    encode.video_variant.resolution
#                )
#            encode.delete()
#    except (OperationalError, ProgrammingError):
        # Tables don't exist yet (e.g., before migrations run)
#        pass
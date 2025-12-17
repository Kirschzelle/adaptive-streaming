from celery import shared_task
from .models import Video, VideoVariant, CurrentEncode, Resolution
from django.core.files import File
from django.db import transaction
import os
import subprocess

@shared_task
def search_videos(query):
    from django.db.models import Q
    results = Video.objects.filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    )

    count = results.count()

    return {
        "query": query,
        "count": count,
        "results": list(results.values("id", "title", "description"))
    }

@shared_task(bind=True)
def encode_video_resolution(video_id, resolution):
    variant = VideoVariant.objects.create(video_id=video_id, resolution=resolution)
    
    current = CurrentEncode.objects.create(
        video_variant=variant,
    )
    
    try:
        video = Video.objects.get(pk=video_id)

        resolution_config = {
            '360p': {'width': 640, 'height': 360, 'minrate': '300k', 'maxrate': '500k', 'avgrate': '400k', 'deadline': 'realtime'},
            '480p': {'width': 854, 'height': 480, 'minrate': '300k', 'maxrate': '1200k', 'avgrate': '800k', 'deadline': 'good'},
            '720p': {'width': 1280, 'height': 720, 'minrate': '300k', 'maxrate': '3000k', 'avgrate': '2000k', 'deadline': 'good'},
            '1080p': {'width': 1920, 'height': 1080, 'minrate': '300k', 'maxrate': '6000k', 'avgrate': '4000k', 'deadline': 'good'},
            '2160p': {'width': 3840, 'height': 2160, 'minrate': '300k', 'maxrate': '18000k', 'avgrate': '12000k', 'deadline': 'good'},
        }
       
        config = resolution_config[resolution]
        input_path = video.video.path
        output_path = f'/tmp/output_{video_id}_{resolution}.webm'

        command = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libvpx-vp9',
            '-b:v', config['avgrate'],
            '-minrate', config['minrate'],
            '-maxrate', config['maxrate'],
            '-vf', f"scale={config['width']}:{config['height']}",
            '-c:a', 'libopus',
            '-b:a', '128k',
            '-cpu-used', '4',
            '-deadline', config['deadline'],
            '-row-mt', '1',
            '-threads', '0',
            '-y',
            output_path
        ]
        
        subprocess.run(command, capture_output=True, text=True, check=True)
        
        with open(output_path, 'rb') as f:
            variant.file.save(f'{video.title}_{resolution}.webm', File(f), save=True)
                
        os.remove(output_path)
    finally:
        current.delete()

@shared_task
def encode_video(video_id):
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=video_id)
        
        if video.processing:
            return
        
        video.processing = True
        video.save(update_fields=['processing'])

    resolutions = [
        Resolution.LOW,
        Resolution.SD,
        Resolution.HD,
        Resolution.FHD,
        Resolution.UHD_4K,
    ]
    
    for i, resolution in enumerate(resolutions):
        encode_video_resolution.apply_async(
            args=[video_id, resolution],
            queue='video_encoding',
            priority=10 - i
        )
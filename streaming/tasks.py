from celery import shared_task
from .models import Video
import os
import shutil
import subprocess
import json
from pathlib import Path
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction

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

@shared_task
def encode_video(video_id):
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=video_id)
        if video.processing:
            return
        video.processing = True
        video.save(update_fields=['processing'])
        
    try:
        input_path = video.video.path
        output_dir = f'/tmp/dash_{video_id}'
        os.makedirs(output_dir, exist_ok=True)
        
        duration_cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            input_path
        ]
        duration_result = subprocess.run(duration_cmd, capture_output=True, text=True, check=True)
        duration_data = json.loads(duration_result.stdout)
        duration = float(duration_data['format']['duration'])

        manifest = 'manifest.mpd'
        
        command = [
            'ffmpeg',
            '-i', input_path,
            # 360p
            '-map', '0:v', '-map', '0:a',
            '-c:v:0', 'libx264', '-b:v:0', '400k', '-s:v:0', '640x360',
            '-profile:v:0', 'high', '-level:v:0', '3.1',
            # 480p
            '-map', '0:v', '-map', '0:a',
            '-c:v:1', 'libx264', '-b:v:1', '800k', '-s:v:1', '854x480',
            '-profile:v:1', 'high', '-level:v:1', '3.1',
            # 720p
            '-map', '0:v', '-map', '0:a',
            '-c:v:2', 'libx264', '-b:v:2', '2000k', '-s:v:2', '1280x720',
            '-profile:v:2', 'high', '-level:v:2', '4.0',
            # 1080p
            '-map', '0:v', '-map', '0:a',
            '-c:v:3', 'libx264', '-b:v:3', '4000k', '-s:v:3', '1920x1080',
            '-profile:v:3', 'high', '-level:v:3', '4.0',
            # Audio
            '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
            # DASH settings
            '-f', 'dash',
            '-seg_duration', '4',
            '-use_template', '1',
            '-use_timeline', '1',
            '-init_seg_name', 'init-$RepresentationID$.m4s',
            '-media_seg_name', 'chunk-$RepresentationID$-$Number$.m4s',
            '-adaptation_sets', 'id=0,streams=v id=1,streams=a',
            '-y',
            os.path.join(output_dir, manifest)
        ]
        
        subprocess.run(command, capture_output=True, text=True, check=True)
        
        dash_dir_name = f'dash/{video_id}'
        
        manifest_path = os.path.join(output_dir, manifest)
        with open(manifest_path, 'rb') as f:
            video.dash_manifest.save(
                f'{dash_dir_name}/{manifest}',
                File(f),
                save=False
            )
        
        for file_name in os.listdir(output_dir):
            if file_name == manifest:
                continue
            
            file_path = os.path.join(output_dir, file_name)
            if os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    video.dash_manifest.storage.save(
                        f'{dash_dir_name}/{file_name}',
                        ContentFile(f.read())
                    )
        
        video.dash_base_path = dash_dir_name
        video.duration = duration
        video.dash_ready = True
        video.processing = False
        video.save(update_fields=['dash_manifest', 'dash_base_path', 'duration', 'dash_ready', 'processing'])
        
        shutil.rmtree(output_dir)
        
    except Exception as e:
        _ = e
        video.processing = False
        video.save(update_fields=['processing'])
        raise
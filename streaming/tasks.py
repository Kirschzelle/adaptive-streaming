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
        
        probe_cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration:stream=codec_type,width,height',
            '-of', 'json',
            input_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(probe_result.stdout)
        duration = float(probe_data['format']['duration'])
        
        video_stream = next((s for s in probe_data['streams'] if s['codec_type'] == 'video'), None)
        if not video_stream:
            raise RuntimeError("No video stream found in input file")
        
        source_width = int(video_stream.get('width', 1920))
        source_height = int(video_stream.get('height', 1080))
                
        all_qualities = [
            {'name': '360p', 'width': 640, 'height': 360, 'bitrate': '400k', 'maxrate': '500k'},
            {'name': '480p', 'width': 854, 'height': 480, 'bitrate': '800k', 'maxrate': '1200k'},
            {'name': '720p', 'width': 1280, 'height': 720, 'bitrate': '2000k', 'maxrate': '3000k'},
            {'name': '1080p', 'width': 1920, 'height': 1080, 'bitrate': '4000k', 'maxrate': '6000k'},
        ]
        
        qualities = [q for q in all_qualities if q['height'] <= source_height]
        
        if not qualities:
            qualities = [{
                'name': 'source',
                'width': source_width,
                'height': source_height,
                'bitrate': '400k',
                'maxrate': '500k'
            }]
        
        video_files = []
        
        for idx, quality in enumerate(qualities):
            video_output = os.path.join(output_dir, f'video_{quality["name"]}.webm')
            
            video_cmd = [
                'ffmpeg',
                '-i', input_path,
                '-c:v', 'libvpx-vp9',
                '-b:v', quality['bitrate'],
                '-minrate', quality['bitrate'],
                '-maxrate', quality['maxrate'],
                '-crf', '31',
                '-vf', f"scale={quality['width']}:{quality['height']}",
                '-cpu-used', '2',
                '-row-mt', '1',
                '-tile-columns', '2',
                '-g', '120',
                '-keyint_min', '120',
                '-sc_threshold', '0',
                '-an',
                '-f', 'webm',
                '-dash', '1',
                '-y',
                video_output
            ]
            
            result = subprocess.run(video_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, video_cmd, result.stdout, result.stderr)
            
            video_files.append(video_output)
        
        audio_output = os.path.join(output_dir, 'audio.webm')
        
        audio_cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vn',
            '-c:a', 'libopus',
            '-b:a', '128k',
            '-ar', '48000',
            '-ac', '2',
            '-f', 'webm',
            '-dash', '1',
            '-y',
            audio_output
        ]
        
        result = subprocess.run(audio_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, audio_cmd, result.stdout, result.stderr)
        
        manifest = 'manifest.mpd'
        all_files = video_files + [audio_output]
        
        dash_inputs = []
        for f in all_files:
            dash_inputs.extend(['-i', f])
        
        map_args = []
        for i in range(len(all_files)):
            map_args.extend(['-map', str(i)])
        
        dash_cmd = [
            'ffmpeg',
            *dash_inputs,
            *map_args,
            '-c', 'copy',
            '-f', 'webm_dash_manifest',
            '-y',
            os.path.join(output_dir, manifest)
        ]
        
        result = subprocess.run(dash_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, dash_cmd, result.stdout, result.stderr)

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
                
    except subprocess.CalledProcessError as e:
        video.processing = False
        video.save(update_fields=['processing'])
        raise
    except Exception as e:
        video.processing = False
        video.save(update_fields=['processing'])
        raise
# Adaptive Media Streaming

Django-based adaptive media streaming application with Celery for background tasks.

## Quick Start

### 1. Setup Environment

Create `.env` file:

```bash
SECRET_KEY=your-secret-key
DEBUG=1
POSTGRES_PASSWORD=your-password
```

### 2. Run Application

```bash
docker compose up --build
```

Access at: http://localhost:8000

### 3. Stop Application

```bash
# Stop services
docker compose down

# Clean reinstall (removes all data)
docker compose down -v && docker compose up --build
```

## Usage

First, click the button shown in `1.1` to create an account or log in. Once logged in, an upload field will appear in the same location, allowing you to choose and upload a video while setting its title and description.

<img width="1280" height="720" alt="Screenshot_2569-01-31_at_09 37 44" src="https://github.com/user-attachments/assets/141bbbed-7fed-4b54-a093-d7acba42098e" />

After a video has been submitted for upload, you can search for it using the search bar shown in `2.1`. Click on any of the results to view the video `2.2`.

<img width="1280" height="720" alt="Screenshot_2569-01-31_at_09 39 01" src="https://github.com/user-attachments/assets/e0254610-6b48-4f24-a490-3b28c55bdcb4" />

`3.1` displays the encoding status of the video. "Original" means it is still encoding and streaming the original video file, while "Dash" indicates that encoding is complete for all resolutions and the Shaka player is being used. `3.2` allows you to run network emulation using real-world traces obtained from [Real-world bandwidth traces (Oboe)](https://github.com/confiwent/Real-world-bandwidth-traces/tree/master/traces_oboe) to simulate different network conditions. 

Once the emulation is finished, open a new terminal and run `docker compose exec web python .\experiments\generate_plots.py <VideoID>`. You can obtain the video ID from the route parameter in the URL. This will generate Quality of Experience reports using [P1203](https://github.com/itu-p1203/itu-p1203) with the [VP9 extension](https://github.com/Telecommunication-Telemedia-Assessment/itu-p1203-codecextension) using profile 0, located at "experiments/P1203_Outputs". You can find graphical representations of the network emulation at "experiments/results/plots".

<img width="1280" height="720" alt="Screenshot_2569-01-31_at_09 39 19" src="https://github.com/user-attachments/assets/5c95f216-a597-42b8-9cda-169432dce41d" />

## Troubleshooting

**Permission error:** `sudo chown -R $(whoami) ~/.docker`​

import sys
import json
import math
import glob
import os
from pathlib import Path
import matplotlib.pyplot as plt
from p1203Pv_extended.p1203Pv_extended import P1203Pv_codec_extended
from itu_p1203 import P1203Standalone

RESULTS_DIR = "experiments/results"
P1203_INPUT_DIR = "experiments/P1203_Inputs"
P1203_OUTPUT_DIR = "experiments/P1203_Outputs"

BITS_TO_KBITS = 1 / 1000;

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def step_series_from_switches(t_rel, y):
    if not t_rel:
        return [], []
    return t_rel, y

def compute_time_weighted_avg_bitrate_kbps(switch_history, play_time_s):
    if not switch_history:
        return None
    points = []
    for switch in switch_history:
        if "timestamp" in switch and "bandwidth" in switch:
            points.append((float(switch["timestamp"]), float(switch["bandwidth"])))
    points.sort(key=lambda switch: switch[0])
    
    if len(points) == 1:
        return points[0][1] * BITS_TO_KBITS
    
    if play_time_s and play_time_s > 0:
        average = 0.0
        for switch_index in range(len(points)):
            start, bandwith = points[switch_index]
            end = points[switch_index + 1][0] if switch_index + 1 < len(points) else play_time_s
            duration = max(0.0, end - start)
            average += duration * bandwith
        
        duration = play_time_s - points[0][0]
        return (average / duration) * BITS_TO_KBITS
    
    raise RuntimeError(f"Did not provide a valid video duration: {play_time_s}")

def estimate_stalls_from_state_history(state_history):
    if not state_history:
        return None, 0, 0.0, 0.0

    buffering = [state for state in state_history if state.get("state") == "buffering"]
    total_buffering = sum(float(x.get("duration", 0.0)) for x in buffering)

    startup = float(buffering[0].get("duration", 0.0)) if buffering else None
    stall_chunks = buffering[1:] if len(buffering) > 1 else []
    stall_time = sum(float(stall.get("duration", 0.0)) for stall in stall_chunks)
    stall_count = len(stall_chunks)

    return startup, stall_count, stall_time, total_buffering

def generate_plots(path):
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    file_name = json_path.stem

    out_dir = json_path.parent / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    network_emulation_results = data.get("appliedNetworkProfile", [])
    timestamps = [float(entry["timestamp_s"]) for entry in network_emulation_results]
    download_rate = [float(entry["download_kbps"]) for entry in network_emulation_results]
    delay = [float(entry["latency_ms"]) for entry in network_emulation_results] if network_emulation_results and "latency_ms" in network_emulation_results[0] else None

    stats = data.get("shakaStatsSnapshot", {}) or {}
    state_history = stats.get("stateHistory", []) or []
    switch_history = stats.get("switchHistory", []) or []
    play_time_s = float(stats.get("playTime", 0.0) or 0.0)
    dropped_frames = int(stats.get("droppedFrames", 0) or 0)

    startup_s, stall_count, stall_time_s, total_buffering_s = estimate_stalls_from_state_history(state_history)

    switch_count = max(0, len(switch_history) - 1) if switch_history else 0

    avg_bitrate_kbps = compute_time_weighted_avg_bitrate_kbps(switch_history, play_time_s)

    # Bandwidth
    plt.figure()
    plt.step(timestamps, download_rate, where="post")
    plt.xlabel("Time (s)")
    plt.ylabel("Download bandwidth (kbps)")
    plt.title(f"Network bandwidth trace — {file_name}")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_dir / f"{file_name}_01_bandwidth.png", dpi=160)
    plt.close()

    # Bandwidth vs bitrate
    switch_points = [(float(switch["timestamp"]), float(switch["bandwidth"]) * BITS_TO_KBITS) for switch in switch_history]
    switch_points.sort(key=lambda x: x[0])

    video_start_epoch = data.get("startedAt") * BITS_TO_KBITS
    switch_timestamp = [entry[0] - video_start_epoch for entry in switch_points]
    switch_bandwith = [entry[1] for entry in switch_points]

    plt.figure()
    plt.step(timestamps, download_rate, where="post", label="Network bandwidth (kbps)")
    switch_timestamp_extended = switch_timestamp + [timestamps[-1]]
    switch_bandwith_extended = switch_bandwith + [switch_bandwith[-1]]
    plt.step(switch_timestamp_extended, switch_bandwith_extended, where="post", label="Selected bitrate (kbps)")

    plt.xlabel("Time (s)")
    plt.ylabel("kbps")
    plt.title(f"Network vs selected bitrate — {file_name}")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_dir / f"{file_name}_02_adaptive.png", dpi=160)
    plt.close()

    # Playback state
    if state_history:
        segments = []
        current_time = 0.0
        for segment in state_history:
            duration = float(segment.get("duration", 0.0))
            state = segment.get("state", "unknown")
            segments.append((current_time, duration, state))
            current_time += max(0.0, duration)

        plt.figure(figsize=(12, 3))
        
        state_colors = {
            'buffering': 'red',
            'playing': 'green',
            'paused': 'yellow',
            'unknown': 'gray'
        }
        
        y = 0
        for (start, duration, state) in segments:
            color = state_colors.get(state, 'gray')
            plt.broken_barh([(start, duration)], (y, 1), 
                        facecolors=color, 
                        edgecolor='black',
                        linewidth=0.5,
                        label=state)

        plt.yticks([y + 0.5], ["State"])
        plt.xlabel("Time (s)")
        plt.ylabel("")
        plt.title(f"Playback state timeline — {file_name}")
        plt.grid(True, axis="x", alpha=0.3)
        plt.xlim(0, current_time)
        
        handles, labels = plt.gca().get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        plt.legend(by_label.values(), by_label.keys(), loc="upper right")
        
        plt.tight_layout()
        plt.savefig(out_dir / f"{file_name}_03_state_timeline.png", dpi=160)
        plt.close()

    buffer_samples = data.get('bufferSamples', [])
    times = []
    buffer_lengths = []
    current_times = []
    estimated_bandwith = []
    stream_bandwith = []
    
    for sample in buffer_samples:
        if sample.get('bufferLength') is not None:
            wall_ms = sample['wall_ms']
            times.append(wall_ms * BITS_TO_KBITS)
            buffer_lengths.append(sample['bufferLength'])
            current_times.append(sample['currentTime'])
            
            if sample.get('estimatedBandwidth'):
                estimated_bandwith.append(sample['estimatedBandwidth'] * BITS_TO_KBITS)
            else:
                estimated_bandwith.append(None)
            
            if sample.get('streamBandwidth'):
                stream_bandwith.append(sample['streamBandwidth'] * BITS_TO_KBITS)
            else:
                stream_bandwith.append(None)
    
    # Buffer Length
    plt.figure(figsize=(12, 6))
    plt.plot(times, buffer_lengths, 'b-', linewidth=2, marker='o', markersize=4)
    plt.xlabel('Time (s)', fontsize=12)
    plt.ylabel('Buffer Length (s)', fontsize=12)
    plt.title(f'Buffer Length Over Time — {file_name}', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / f'{file_name}_04_buffer_length.png', dpi=160)
    plt.close()

    # Summary
    plt.figure()
    labels = [
        "Startup buffering (s)",
        "Stall time (s)",
        "Stall count",
        "Switch count",
        "Dropped frames",
    ]
    values = [
        float(startup_s or 0.0),
        float(stall_time_s or 0.0),
        float(stall_count or 0),
        float(switch_count or 0),
        float(dropped_frames or 0),
    ]
    plt.bar(labels, values)
    plt.xticks(rotation=20, ha="right")
    plt.title(f"QoE metric summary — {file_name}")
    plt.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(out_dir / f"{file_name}_05_qoe_summary.png", dpi=160)
    plt.close()

def generate_all_plots(prefix):
    result_pattern = os.path.join(RESULTS_DIR, f"video_{prefix}*.json")
    result_files = sorted(glob.glob(result_pattern))

    if not result_files:
        print(f"No json files found: {result_pattern}. Did you fail to run the network emulation or type the wrong video_id?")
        sys.exit(1)

    for json_path in result_files:
        try:
            generate_plots(json_path)
        except Exception as e:
            print(f"Plot generation failed for {json_path}: {e}")
            continue

def generate_all_QoE(prefix):
    os.makedirs(P1203_OUTPUT_DIR, exist_ok=True)

    p1203_input_pattern = os.path.join(P1203_INPUT_DIR, f"video_{prefix}*.json")
    input_files = sorted(glob.glob(p1203_input_pattern))

    if not input_files:
        print(f"No json files found: {p1203_input_pattern}. Did you fail to run the network emulation or type the wrong video_id?")
        sys.exit(1)
    
    P1203Pv_codec_extended._show_warning = False

    for input_path in input_files:
        try:
            with open(input_path, 'r') as f:
                input_data = json.load(f)
            
            p1203 = P1203Standalone(input_data, Pv=P1203Pv_codec_extended)
            results = p1203.calculate_complete()
            
            base_name = Path(input_path).stem.replace("_p1203_input", "")
            output_path = os.path.join(P1203_OUTPUT_DIR, f"{base_name}_p1203_output.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
                                    
        except Exception as e:
            print(f"P1203 failed for {input_path}: {e}")
            continue

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: docker compose exec web python experiments/generate_plots.py <video_id>")
        sys.exit(1)

    prefix = sys.argv[1]

    generate_all_plots(prefix)
    generate_all_QoE(prefix)
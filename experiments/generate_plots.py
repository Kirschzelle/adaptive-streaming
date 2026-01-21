import sys
import json
import math
import glob
from pathlib import Path
import matplotlib.pyplot as plt

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def step_series_from_switches(t_rel, y):
    if not t_rel:
        return [], []
    return t_rel, y


def compute_time_weighted_avg_bitrate_kbps(switch_history, fallback_play_time_s):
    if not switch_history:
        return None

    pts = []
    for s in switch_history:
        if "timestamp" in s and "bandwidth" in s:
            pts.append((float(s["timestamp"]), float(s["bandwidth"])))
    pts.sort(key=lambda x: x[0])

    if len(pts) == 1:
        return pts[0][1] / 1000.0

    total_dur = pts[-1][0] - pts[0][0]
    if total_dur <= 0 and fallback_play_time_s:
        total_dur = float(fallback_play_time_s)

    if total_dur and total_dur > 0:
        acc = 0.0
        for i in range(len(pts)):
            t_i, bw_i = pts[i]
            t_next = pts[i + 1][0] if i + 1 < len(pts) else (pts[0][0] + total_dur)
            dt = max(0.0, t_next - t_i)
            acc += dt * bw_i
        return (acc / total_dur) / 1000.0

    return (sum(bw for _, bw in pts) / len(pts)) / 1000.0


def estimate_stalls_from_state_history(state_history):
    if not state_history:
        return None, 0, 0.0, 0.0

    buffering = [x for x in state_history if x.get("state") == "buffering"]
    total_buffering = sum(float(x.get("duration", 0.0)) for x in buffering)

    startup = float(buffering[0].get("duration", 0.0)) if buffering else None
    stall_chunks = buffering[1:] if len(buffering) > 1 else []
    stall_time = sum(float(x.get("duration", 0.0)) for x in stall_chunks)
    stall_count = len(stall_chunks)

    return startup, stall_count, stall_time, total_buffering


def qoe_mos_proxy(startup_s, stall_time_s, stall_count, switch_count, avg_bitrate_kbps, dropped_frames):
    startup_s = float(startup_s) if startup_s is not None else 0.0
    stall_time_s = float(stall_time_s or 0.0)
    stall_count = int(stall_count or 0)
    switch_count = int(switch_count or 0)
    dropped_frames = int(dropped_frames or 0)

    if avg_bitrate_kbps is None:
        bitrate_term = 0.0
    else:
        bitrate_term = 0.6 * math.log10(1.0 + (avg_bitrate_kbps / 300.0))

    startup_pen = 0.35 * startup_s
    stall_pen = 2.2 * stall_time_s + 0.8 * stall_count
    switch_pen = 0.06 * switch_count
    drop_pen = 0.02 * dropped_frames

    mos = 5.0 + bitrate_term - startup_pen - stall_pen - switch_pen - drop_pen
    return clamp(mos, 0.0, 5.0)

def generate_plots(path):
    json_path = Path(path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    stem = json_path.stem

    out_dir = json_path.parent / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    net = data.get("appliedNetworkProfile", [])
    net_t = [float(p["timestamp_s"]) for p in net]
    net_bw = [float(p["download_kbps"]) for p in net]
    net_rtt = [float(p["latency_ms"]) for p in net] if net and "latency_ms" in net[0] else None

    stats = data.get("shakaStatsSnapshot", {}) or {}
    state_history = stats.get("stateHistory", []) or []
    switch_history = stats.get("switchHistory", []) or []
    play_time_s = float(stats.get("playTime", 0.0) or 0.0)
    dropped_frames = int(stats.get("droppedFrames", 0) or 0)

    startup_s, stall_count, stall_time_s, total_buffering_s = estimate_stalls_from_state_history(state_history)

    switch_count = max(0, len(switch_history) - 1) if switch_history else 0

    avg_bitrate_kbps = compute_time_weighted_avg_bitrate_kbps(switch_history, fallback_play_time_s=play_time_s)

    mos = qoe_mos_proxy(
        startup_s=startup_s,
        stall_time_s=stall_time_s,
        stall_count=stall_count,
        switch_count=switch_count,
        avg_bitrate_kbps=avg_bitrate_kbps,
        dropped_frames=dropped_frames,
    )

    # -------- Plot 1: Bandwidth trace --------
    plt.figure()
    plt.step(net_t, net_bw, where="post")
    plt.xlabel("Time (s)")
    plt.ylabel("Download bandwidth (kbps)")
    plt.title(f"Network bandwidth trace — {stem}")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(out_dir / f"{stem}_01_bandwidth.png", dpi=160)
    plt.close()

    # Optional: RTT plot (nice for QoE context)
    if net_rtt is not None:
        plt.figure()
        plt.step(net_t, net_rtt, where="post")
        plt.xlabel("Time (s)")
        plt.ylabel("Latency / RTT (ms)")
        plt.title(f"Network latency trace — {stem}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_01b_latency.png", dpi=160)
        plt.close()

    # -------- Plot 2: Overlay bandwidth vs bitrate --------
    sw_pts = [(float(s["timestamp"]), float(s["bandwidth"]) / 1000.0) for s in switch_history]
    sw_pts.sort(key=lambda x: x[0])

    if sw_pts:
        video_start_epoch = data.get("startedAt") / 1000.0
        sw_t = [p[0] - video_start_epoch for p in sw_pts]
        sw_b = [p[1] for p in sw_pts]

        plt.figure()
        plt.step(net_t, net_bw, where="post", label="Network bandwidth (kbps)")
        if sw_t and net_t:
            sw_t_extended = sw_t + [net_t[-1]]
            sw_b_extended = sw_b + [sw_b[-1]]
            plt.step(sw_t_extended, sw_b_extended, where="post", label="Selected bitrate (kbps)")
        else:
            plt.step(sw_t, sw_b, where="post", label="Selected bitrate (kbps)")

        plt.xlabel("Time (s)")
        plt.ylabel("kbps")
        plt.title(f"Network vs selected bitrate — {stem}")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_02_adaptive.png", dpi=160)
        plt.close()

    # -------- Plot 3: Playback state timeline --------
    if state_history:
        t0s = float(state_history[0]["timestamp"])
        segments = []
        cur_t = 0.0
        for seg in state_history:
            dur = float(seg.get("duration", 0.0))
            st = seg.get("state", "unknown")
            segments.append((cur_t, dur, st))
            cur_t += max(0.0, dur)

        plt.figure(figsize=(12, 3))  # Make it wider and shorter
        
        # Define distinct colors for each state
        state_colors = {
            'buffering': 'red',
            'playing': 'green',
            'paused': 'yellow',
            'unknown': 'gray'
        }
        
        y = 0
        for (start, dur, st) in segments:
            color = state_colors.get(st, 'gray')
            plt.broken_barh([(start, dur)], (y, 1), 
                        facecolors=color, 
                        edgecolor='black',
                        linewidth=0.5,
                        label=st)

        plt.yticks([y + 0.5], ["State"])
        plt.xlabel("Time (s)")
        plt.ylabel("")
        plt.title(f"Playback state timeline — {stem}")
        plt.grid(True, axis="x", alpha=0.3)
        plt.xlim(0, cur_t)  # Set explicit x-axis limits
        
        # Create legend with unique states only
        handles, labels = plt.gca().get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        plt.legend(by_label.values(), by_label.keys(), loc="upper right")
        
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_03_state_timeline.png", dpi=160)
        plt.close()

    buffer_samples = data.get('bufferSamples', [])
    times = []
    buffer_lengths = []
    current_times = []
    estimated_bw = []
    stream_bw = []
    
    for sample in buffer_samples:
        if sample.get('bufferLength') is not None:
            wall_ms = sample['wall_ms']
            times.append(wall_ms / 1000.0)
            buffer_lengths.append(sample['bufferLength'])
            current_times.append(sample['currentTime'])
            
            if sample.get('estimatedBandwidth'):
                estimated_bw.append(sample['estimatedBandwidth'] / 1000.0)
            else:
                estimated_bw.append(None)
            
            if sample.get('streamBandwidth'):
                stream_bw.append(sample['streamBandwidth'] / 1000.0)
            else:
                stream_bw.append(None)
    
    net = data.get("appliedNetworkProfile", [])
    net_t = [float(p["timestamp_s"]) for p in net]
    net_bw = [float(p["download_kbps"]) for p in net]
    
    # -------- Plot 4: Buffer Length Over Time --------
    plt.figure(figsize=(12, 6))
    plt.plot(times, buffer_lengths, 'b-', linewidth=2, marker='o', markersize=4)
    plt.xlabel('Time (s)', fontsize=12)
    plt.ylabel('Buffer Length (s)', fontsize=12)
    plt.title(f'Buffer Length Over Time — {stem}', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / f'{stem}_04_buffer_length.png', dpi=160)
    plt.close()

    # -------- Plot 5: QoE summary bar chart --------
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
    plt.title(f"QoE metric summary — {stem}")
    plt.grid(True, axis="y")
    plt.tight_layout()
    plt.savefig(out_dir / f"{stem}_05_qoe_summary.png", dpi=160)
    plt.close()

    summary = {
        "run": stem,
        "tracePath": data.get("tracePath"),
        "durationRequestedS": data.get("durationRequestedS"),
        "playTimeS": play_time_s,
        "startupBufferingS": startup_s,
        "stallCount": stall_count,
        "stallTimeS": stall_time_s,
        "totalBufferingS": total_buffering_s,
        "switchCount": switch_count,
        "droppedFrames": dropped_frames,
        "avgSelectedBitrateKbps_timeWeighted": avg_bitrate_kbps,
        "qoeMOS_proxy_0to5": mos,
    }
    (out_dir / f"{stem}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"[OK] Plots written to: {out_dir}")
    print(f"[OK] Summary: {out_dir / (stem + '_summary.json')}")
    print("----- QoE Summary -----")
    print(f"Startup buffering: {startup_s:.3f} s" if startup_s is not None else "Startup buffering: n/a")
    print(f"Stall count:       {stall_count}")
    print(f"Stall time:        {stall_time_s:.3f} s")
    print(f"Switch count:      {switch_count}")
    print(f"Dropped frames:    {dropped_frames}")
    if avg_bitrate_kbps is not None:
        print(f"Avg bitrate:       {avg_bitrate_kbps:.1f} kbps (time-weighted)")
    print(f"QoE MOS (proxy):   {mos:.2f} / 5.00")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: docker compose exec web python experiments/generate_plots.py experiments/results/video_<id>")
        sys.exit(1)

    prefix = sys.argv[1]
    pattern = f"{prefix}*.json"
    matching_files = sorted(glob.glob(pattern))

    if not matching_files:
        print(f"No JSON files found matching: {pattern}")
        sys.exit(1)

    print(f"Found {len(matching_files)} result files")
    for json_path in matching_files:
        generate_plots(json_path)
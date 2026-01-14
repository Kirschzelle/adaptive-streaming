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
        return pts[0][1] / 1000.0  # kbps

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
        return (acc / total_dur) / 1000.0  # kbps

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

    # -------- Plot 2: Selected bitrate over time --------
    # Convert epoch timestamps to relative seconds using first switch timestamp as t0
    sw_pts = [(float(s["timestamp"]), float(s["bandwidth"]) / 1000.0) for s in switch_history]  # kbps
    sw_pts.sort(key=lambda x: x[0])

    if sw_pts:
        t0 = sw_pts[0][0]
        sw_t = [p[0] - t0 for p in sw_pts]
        sw_b = [p[1] for p in sw_pts]

        plt.figure()
        plt.step(sw_t, sw_b, where="post")
        plt.xlabel("Time since first switch (s)")
        plt.ylabel("Selected bitrate (kbps)")
        plt.title(f"Adaptive bitrate (ABR) selection — {stem}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_02_selected_bitrate.png", dpi=160)
        plt.close()

        # -------- Plot 3: Overlay bandwidth vs bitrate --------
        plt.figure()
        plt.step(net_t, net_bw, where="post", label="Network bandwidth (kbps)")
        plt.step(sw_t, sw_b, where="post", label="Selected bitrate (kbps)")
        plt.xlabel("Time (s)")
        plt.ylabel("kbps")
        plt.title(f"Network vs selected bitrate — {stem}")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_03_overlay.png", dpi=160)
        plt.close()

    # -------- Plot 4: Playback state timeline --------
    if state_history:
        t0s = float(state_history[0]["timestamp"])
        segments = []
        cur_t = 0.0
        for seg in state_history:
            dur = float(seg.get("duration", 0.0))
            st = seg.get("state", "unknown")
            segments.append((cur_t, dur, st))
            cur_t += max(0.0, dur)

        plt.figure()
        y = 0
        for (start, dur, st) in segments:
            plt.broken_barh([(start, dur)], (y, 5), label=st)

        plt.yticks([y + 2.5], ["playback"])
        plt.xlabel("Time (s) (relative)")
        plt.title(f"Playback state timeline (buffering/playing) — {stem}")
        plt.grid(True, axis="x")
        handles, labels = plt.gca().get_legend_handles_labels()
        uniq = []
        seen = set()
        for h, l in zip(handles, labels):
            if l not in seen:
                uniq.append((h, l))
                seen.add(l)
        if uniq:
            plt.legend([x[0] for x in uniq], [x[1] for x in uniq], loc="upper right")
        plt.tight_layout()
        plt.savefig(out_dir / f"{stem}_04_state_timeline.png", dpi=160)
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
    #for json_path in matching_files:
        #generate_plots(json_path)
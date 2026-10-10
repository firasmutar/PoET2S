"""All figures for the revised manuscript (v18). Captions live in the paper;
no figure carries a baked-in number. Sized for an 8.4 cm journal column.

Colour: the four twin-committee schemes use fixed categorical slots
(validated palette); classical baselines are neutral grey with PoET2S
highlighted, since each bar is named on its axis. No dual-axis charts.
"""
from __future__ import annotations

import csv
import random
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = RES / "figures_v18"
OUT.mkdir(exist_ok=True)

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GREY, INK, MUTED = "#9a9990", "#262624", "#6b6a64"
TWIN = {"PoET2S": BLUE, "PoMonitor": ORANGE, "EACM": AQUA, "RepStake": YELLOW}
LABEL = {"PoET2S": "PoET²S", "PoMonitor": "Veto (PoMonitor)", "EACM": "Additive (EACM-style)",
         "RepStake": "Linear (RepStake)"}
SHORT = {"PoET2S": "PoET²S", "PoMonitor": "Veto", "EACM": "Additive", "RepStake": "Linear"}
W = 3.35   # inches, one column

plt.rcParams.update({
    "font.size": 7, "axes.titlesize": 7, "axes.labelsize": 7, "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5, "legend.fontsize": 6.5, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#e6e5df", "grid.linewidth": 0.5, "axes.axisbelow": True,
    "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.03,
})


def load(name):
    return list(csv.DictReader(open(RES / name)))


def per_seed(rows, scheme, metric, key="scheme"):
    return [float(r[metric]) for r in rows if r[key] == scheme]


def save(fig, name):
    fig.savefig(OUT / name)
    plt.close(fig)
    print("  wrote", name)


def fig_validation():
    from poet2s_sim.grid_model import build_grid, DigitalTwin
    from poet2s_sim.protocols import PBFT
    from poet2s_sim.sim_core import DEScheduler, Network
    vs, ms = [], []
    for n in (60, 100, 250, 500, 1000, 2000):
        rng = random.Random(42)
        nodes = build_grid(n, 0.15, rng)
        sched = DEScheduler()
        net = Network(sched, n, rng=random.Random(1042))
        p = PBFT(sched, net, nodes, DigitalTwin(), rng=random.Random(2042))
        p.propose_block()
        sched.run_until(120000)
        vs.append(p.V)
        ms.append(net.messages_sent)
    fig, ax = plt.subplots(figsize=(W, 2.1))
    vf = np.logspace(np.log10(min(vs)), np.log10(max(vs)), 100)
    ax.loglog(vf, 2 * vf * (vf - 1), color=MUTED, lw=1.2, label="Castro–Liskov: 2V(V − 1)")
    ax.loglog(vs, ms, "o", ms=5, color=BLUE, mec="white", mew=1, label="Simulator (measured)")
    for i, (v, m) in enumerate(zip(vs, ms)):
        last, first = i == len(vs) - 1, i == 0   # keep the end labels inside the axes
        xy, va, ha = ((-7, 0), "center", "right") if last else (((7, 2), "bottom", "left") if first else ((7, -2), "top", "left"))
        ax.annotate(f"{m:,}", (v, m), xytext=xy, textcoords="offset points", fontsize=5.5, color=MUTED, va=va, ha=ha)
    slope = np.polyfit(np.log(vs), np.log(ms), 1)[0]
    ax.set_xlabel("Validators V")
    ax.set_ylabel("Messages per block")
    ax.legend(frameon=False, loc="upper left")
    ax.text(0.98, 0.05, f"log–log slope {slope:.2f}", transform=ax.transAxes, ha="right", fontsize=6.5, color=MUTED)
    save(fig, "fig01_validation.png")
    return vs, ms, slope


BASE_ORDER = ["PoS", "PoS+Twin", "DPoS", "DPoS+Twin", "PBFT", "PBFT+Twin", "PoET2S"]


def bar_panel(ax, names, means, sds, fmt, highlight="PoET2S", xlabel="", ref=None):
    y = np.arange(len(names))
    colors = [BLUE if n == highlight else GREY for n in names]
    ax.barh(y, means, xerr=sds, color=colors, height=0.62, edgecolor="white", linewidth=1,
            error_kw={"elinewidth": 0.7, "ecolor": INK, "capsize": 1.5})
    ax.set_yticks(y)
    ax.set_yticklabels([LABEL.get(n, n) if n in TWIN else n for n in names])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    hi = max(m + s for m, s in zip(means, sds))
    for yi, m, s in zip(y, means, sds):
        ax.text(m + s + hi * 0.02, yi, fmt.format(m), va="center", fontsize=6, color=INK)
    ax.set_xlim(0, hi * 1.22)
    if ref is not None:
        ax.axvline(ref, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    ax.set_xlabel(xlabel)


def fig_latency(main):
    fp = load("fastpath_main.csv")
    def ms(rows, scheme, metric):
        x = [float(r[metric]) for r in rows if r["scheme"] == scheme]
        return st.mean(x), st.stdev(x)
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.2), sharey=True, gridspec_kw={"width_ratios": [1, 1]})
    names = ["PoS", "DPoS", "PBFT", "PoET2S", "PoET2S-fast"]
    labels = ["PoS", "DPoS", "PBFT", "PoET²S", "PoET²S fast"]
    for ax, metric, title in ((a, "latency_ms", "(a) Block final (quorum)"), (b, "first_commit_ms", "(b) First commit proof")):
        vals = [ms(fp, n, metric) for n in names]
        y = np.arange(len(names))
        cols = [BLUE if n.startswith("PoET2S") else GREY for n in names]
        ax.barh(y, [v[0] for v in vals], xerr=[v[1] for v in vals], color=cols, height=0.62, edgecolor="white",
                linewidth=1, error_kw={"elinewidth": 0.7, "ecolor": INK, "capsize": 1.5})
        for bar, n in zip(ax.patches, names):
            if n == "PoET2S-fast":
                bar.set_hatch("////"); bar.set_edgecolor("white")
        for yi, (m, sd) in zip(y, vals):
            ax.text(m + sd + 1.0, yi, f"{m:.1f}", va="center", fontsize=6, color=INK)
        ax.set_yticks(y); ax.set_yticklabels(labels); ax.invert_yaxis()
        ax.grid(axis="y", visible=False); ax.set_xlim(0, 50)
        ax.set_title(title, loc="left"); ax.set_xlabel("Latency (ms)")
    b.tick_params(labelleft=False)
    fig.tight_layout(w_pad=0.8)
    save(fig, "fig02_latency.png")


def fig_detection(main):
    names = BASE_ORDER
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.1), sharey=True)
    bar_panel(a, names, [st.mean(per_seed(main, n, "caught_pct")) for n in names],
              [st.stdev(per_seed(main, n, "caught_pct")) for n in names], "{:.1f}", xlabel="Attackers caught (%)")
    bar_panel(b, names, [st.mean(per_seed(main, n, "fp_per_caught")) for n in names],
              [st.stdev(per_seed(main, n, "fp_per_caught")) for n in names], "{:.1f}",
              xlabel="False positives per catch")
    b.tick_params(labelleft=False)
    a.set_xlim(0, 128)
    a.set_title("(a) Coverage", loc="left")
    b.set_title("(b) Cost", loc="left")
    fig.tight_layout(w_pad=1.4)
    save(fig, "fig03_detection.png")


def fig_infiltration_baselines(main):
    names = ["PoW"] + BASE_ORDER
    m = [st.mean(per_seed(main, n, "infiltration_pct")) for n in names]
    s = [st.stdev(per_seed(main, n, "infiltration_pct")) for n in names]
    fig, ax = plt.subplots(figsize=(W, 2.15))
    bar_panel(ax, names, m, s, "{:.1f}", xlabel="Malicious share of the validating set (%)", ref=15.0)
    ax.text(15.3, len(names) - 0.6, "15% = population share", fontsize=5.8, color=MUTED, va="bottom")
    save(fig, "fig04_infiltration_baselines.png")


FAM = ["PoMonitor", "EACM", "RepStake", "PoET2S"]


def fig_design_points(main):
    fig, axes = plt.subplots(1, 3, figsize=(W, 1.75), sharey=True)
    specs = [("caught_pct", "Caught (%)", "{:.1f}"), ("fp_per_caught", "FP per catch", "{:.1f}"),
             ("infiltration_pct", "Infiltration (%)", "{:.1f}")]
    y = np.arange(len(FAM))
    for ax, (metric, lab, fmt) in zip(axes, specs):
        means = [st.mean(per_seed(main, n, metric)) for n in FAM]
        sds = [st.stdev(per_seed(main, n, metric)) for n in FAM]
        ax.barh(y, means, xerr=sds, color=[TWIN[n] for n in FAM], height=0.62, edgecolor="white",
                linewidth=1, error_kw={"elinewidth": 0.7, "ecolor": INK, "capsize": 1.5})
        hi = max(m + s for m, s in zip(means, sds))
        for yi, mm, ss in zip(y, means, sds):
            ax.text(mm + ss + hi * 0.03, yi, fmt.format(mm), va="center", fontsize=5.8)
        ax.set_xlim(0, hi * 1.35)
        ax.set_xlabel(lab)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([SHORT[n] for n in FAM])
    axes[0].invert_yaxis()
    fig.tight_layout(w_pad=0.4)
    save(fig, "fig05_design_points.png")


def fig_pairs(main):
    seeds = sorted({int(r["seed"]) for r in main})
    pe = per_seed(main, "PoET2S", "infiltration_pct")
    fig, axes = plt.subplots(1, 2, figsize=(W, 1.9), sharey=True)
    for ax, other in zip(axes, ["PoMonitor", "RepStake"]):
        ot = per_seed(main, other, "infiltration_pct")
        order = np.argsort(ot)
        x = np.arange(len(seeds))
        for xi, i in zip(x, order):
            ax.plot([xi, xi], [ot[i], pe[i]], color="#d4d3cc", lw=0.7, zorder=1)
        ax.scatter(x, np.array(ot)[order], s=9, color=TWIN[other], edgecolor="white", lw=0.5, zorder=2,
                   label=SHORT[other])
        ax.scatter(x, np.array(pe)[order], s=9, color=BLUE, edgecolor="white", lw=0.5, zorder=3, label="PoET²S")
        wins = sum(1 for a, b in zip(pe, ot) if a < b)
        ax.set_title(f"({'ab'[['PoMonitor','RepStake'].index(other)]}) vs {SHORT[other].lower()}: lower on {wins}/{len(seeds)}", loc="left", fontsize=6.3)
        ax.set_xticks([])
        ax.set_xlabel("Seeds (sorted)")
        ax.grid(axis="x", visible=False)
        ax.legend(frameon=False, loc="upper left", handletextpad=0.2)
    axes[0].set_ylabel("Infiltration (%)")
    fig.tight_layout(w_pad=0.5)
    save(fig, "fig06_pairs.png")


def fig_trajectory():
    rows = load("weight_trajectory.csv")
    lies = sorted({float(r["lie"]) for r in rows})
    ramp = ["#9a9990", "#86b6ef", "#5598e7", "#2a78d6", "#104281"]  # honest grey, then light->dark blue
    fig, axes = plt.subplots(2, 2, figsize=(W, 2.9))
    (a, b), (c, d) = axes
    for lie, col in zip(lies, ramp):
        sub = [r for r in rows if float(r["lie"]) == lie]
        t = [int(r["slot"]) for r in sub]
        lab = "honest" if lie == 1.0 else f"×{lie:g}"
        a.plot(t, [float(r["tts"]) for r in sub], color=col, lw=1.1, label=lab)
        b.plot(t, [float(r["energy_rel"]) for r in sub], color=col, lw=1.1)
        c.plot(t, [float(r["poet2s_rel"]) for r in sub], color=col, lw=1.1)
    for ax in (a, b, c):
        ax.axvline(12, color=MUTED, lw=0.6, ls=(0, (2, 2)))
        ax.set_xlabel("Slot")
    a.set_ylabel("TTS")
    a.set_title("(a) Trust score", loc="left")
    b.set_ylabel("e / e(honest)")
    b.set_title("(b) Verified energy term", loc="left")
    c.set_ylabel("W / W(honest)")
    c.set_title("(c) PoET²S weight", loc="left")
    h, l = a.get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=5.8, ncol=5, loc="lower center", handlelength=1.4, columnspacing=1.0, title="Lie factor from slot 12", title_fontsize=5.8)
    # (d) mean relative weight after slot 36 under each rule, by lie size
    rules = [("veto", "Veto (eligible-slot share)", ORANGE), ("linear", "Linear (γ=1)", YELLOW), ("poet2s", "PoET²S (γ=2.5)", BLUE)]
    xs = np.arange(len(lies))
    wbar = 0.26
    for k, (key, lab, col) in enumerate(rules):
        vals = []
        for lie in lies:
            sub = [r for r in rows if float(r["lie"]) == lie and int(r["slot"]) >= 36]
            if key == "veto":
                hon = [r for r in rows if float(r["lie"]) == 1.0 and int(r["slot"]) >= 36]
                base = np.mean([1.0 if float(r["anomaly"]) <= 0.5 else 0.0 for r in hon])
                vals.append(np.mean([1.0 if float(r["anomaly"]) <= 0.5 else 0.0 for r in sub]) / base)
            else:
                vals.append(np.mean([float(r[f"{key}_rel"]) for r in sub]))
        d.bar(xs + (k - 1) * wbar, vals, width=wbar, color=col, edgecolor="white", lw=0.6, label=lab)
    d.set_xticks(xs)
    d.set_xticklabels(["1" if l == 1.0 else f"{l:g}" for l in lies])
    d.set_xlabel("Lie factor")
    d.set_ylim(0, 1.95)
    d.set_title("(d) Slots 36–71, by lie size", loc="left")
    d.set_ylabel("Share of honest weight")
    d.legend(frameon=False, fontsize=5.3, loc="upper left", ncol=1, handlelength=1, borderaxespad=0.1)
    d.grid(axis="x", visible=False)
    fig.tight_layout(h_pad=0.6, w_pad=0.6, rect=(0, 0.1, 1, 1))
    save(fig, "fig07_trajectory.png")


def fig_byzantine():
    rows = load("byzantine_sweep.csv")
    fr = sorted({float(r["fraction"]) for r in rows})
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.0))
    x = [100 * f for f in fr]
    a.plot(x, x, color=MUTED, lw=0.8, ls=(0, (3, 2)))
    for s in ["PoMonitor", "EACM", "RepStake", "PoET2S"]:
        y = [st.mean(float(r["infiltration_pct"]) for r in rows if float(r["fraction"]) == f and r["scheme"] == s) for f in fr]
        v = [st.mean(float(r["safety_violation_pct"]) for r in rows if float(r["fraction"]) == f and r["scheme"] == s) for f in fr]
        a.plot(x, y, "o-", ms=2.8, lw=1.2, color=TWIN[s], mec="white", mew=0.5, label=SHORT[s])
        b.plot(x, v, "o-", ms=2.8, lw=1.2, color=TWIN[s], mec="white", mew=0.5)
    a.set_title("(a) Infiltration", loc="left")
    b.set_title("(b) Blocks with ≥ 1/3 Byzantine", loc="left")
    a.set_ylabel("Share (%)")
    for ax in (a, b):
        ax.set_xlabel("Byzantine fraction (%)")
        ax.set_xticks([10, 20, 30, 40])
    a.legend(frameon=False, loc="upper left", fontsize=5.8, handlelength=1.2)
    fig.tight_layout(w_pad=0.8)
    save(fig, "fig08_byzantine.png")


def fig_matched_fp():
    rows = load("matched_fp.csv")
    main = load("main_per_seed.csv")
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.0))
    def pts(scheme, par):
        vals = sorted({float(r["value"]) for r in rows if r["scheme"] == scheme and r["param"] == par})
        out = []
        for v in vals:
            sub = [r for r in rows if r["scheme"] == scheme and r["param"] == par and float(r["value"]) == v]
            out.append(tuple(st.mean(float(r[m]) for r in sub) for m in ("fp_per_caught", "caught_pct", "infiltration_pct")))
        return out
    series = [("PoMonitor", "veto_threshold", "Veto (threshold)"), ("EACM", "trust_floor", "Additive (floor)"),
              ("PoET2S", "tts_reject", "PoET²S (τ)"), ("PoET2S", "eta", "PoET²S (η)")]
    for scheme, par, lab in series:
        P = pts(scheme, par)
        if scheme == "PoET2S":  # add the default operating point
            P.append(tuple(st.mean(per_seed(main, "PoET2S", m)) for m in ("fp_per_caught", "caught_pct", "infiltration_pct")))
        P.sort()
        ls = "none" if par == "tts_reject" else ("-" if par != "eta" else (0, (2, 1.5)))
        for ax, k in ((a, 1), (b, 2)):
            ax.plot([q[0] for q in P], [q[k] for q in P], marker="o", ms=2.6, lw=1.1, ls=ls, color=TWIN[scheme],
                    mec="white", mew=0.4, label=lab)
    a.set_title("(a) Coverage", loc="left"); a.set_ylabel("Attackers caught (%)")
    b.set_title("(b) Infiltration", loc="left"); b.set_ylabel("Infiltration (%)")
    for ax in (a, b):
        ax.set_xlabel("False positives per catch")
    b.legend(frameon=False, fontsize=5.3, loc="upper right", handlelength=1.6)
    fig.tight_layout(w_pad=0.8)
    save(fig, "fig12_matched_fp.png")


def fig_adaptive():
    rows = load("adaptive.csv")
    regs = ["static", "recover", "stealth"]
    labs = ["Static", "Lie-and-\nrecover", "Stealth"]
    fig, axes = plt.subplots(1, 2, figsize=(W, 1.9))
    x = np.arange(3)
    w = 0.36
    for ax, metric, ylab in [(axes[0], "infiltration_pct", "Infiltration (%)"),
                             (axes[1], "extracted_profit", "Profit proxy (Σ over-report)")]:
        for k, s in enumerate(["PoMonitor", "PoET2S"]):
            m = [st.mean(per_seed(rows, f"{s}-{r}", metric)) for r in regs]
            sd = [st.stdev(per_seed(rows, f"{s}-{r}", metric)) for r in regs]
            ax.bar(x + (k - 0.5) * w, m, yerr=sd, width=w, color=TWIN[s], edgecolor="white", lw=0.8,
                   error_kw={"elinewidth": 0.7, "ecolor": INK, "capsize": 1.5}, label=SHORT[s])
            for xi, mm, ss in zip(x, m, sd):
                ax.text(xi + (k - 0.5) * w, mm + ss + max(m) * 0.03, f"{mm:.1f}", ha="center", fontsize=5.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labs)
        ax.set_ylabel(ylab)
        ax.grid(axis="x", visible=False)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, loc="upper center", ncol=2)
    fig.tight_layout(w_pad=0.8, rect=(0, 0, 1, 0.9))
    save(fig, "fig09_adaptive.png")


def fig_sensitivity():
    rows = load("param_sensitivity.csv")
    params = [("committee_size", "K"), ("gamma", "γ"), ("eta", "η"), ("tts_reject", "τ")]
    top = {"committee_size": ("latency_ms", "Latency (ms)"), "gamma": ("infiltration_pct", "Infiltration (%)"),
           "eta": ("caught_pct", "Caught (%)"), "tts_reject": ("caught_pct", "Caught (%)")}
    bot = {"committee_size": ("infiltration_pct", "Infiltration (%)"), "gamma": ("caught_pct", "Caught (%)"),
           "eta": ("fp_per_caught", "FP per catch"), "tts_reject": ("fp_per_caught", "FP per catch")}
    fig, axes = plt.subplots(2, 4, figsize=(W * 1.0, 2.6))
    for j, (p, sym) in enumerate(params):
        sub = sorted([r for r in rows if r["parameter"] == p], key=lambda r: float(r["value"]))
        xv = [float(r["value"]) for r in sub]
        dflt = [float(r["value"]) for r in sub if r["is_default"] == "True"][0]
        for i, spec in enumerate((top[p], bot[p])):
            ax = axes[i, j]
            yv = [float(r[spec[0]]) for r in sub]
            ax.plot(xv, yv, "o-", color=BLUE, ms=3, lw=1.1, mec="white", mew=0.5)
            dv = yv[xv.index(dflt)]
            ax.plot([dflt], [dv], "o", ms=4.5, color=INK, mec="white", mew=0.6, zorder=3)
            ax.set_title(spec[1], loc="left", fontsize=6.3)
            ax.tick_params(labelsize=5.5)
            if i == 1:
                ax.set_xlabel(sym)
            lo, hi = min(yv), max(yv)
            pad = max((hi - lo) * 0.15, abs(hi) * 0.02 + 0.1)
            ax.set_ylim(lo - pad, hi + pad)
    fig.tight_layout(h_pad=0.5, w_pad=0.4)
    save(fig, "fig10_sensitivity.png")


def fig_scaling():
    rows = load("scaling.csv")
    ns = sorted({int(r["N"]) for r in rows})
    col = {"PoS": GREY, "DPoS": "#6b6a64", "PBFT": ORANGE, "PoET2S": BLUE}
    fig, axes = plt.subplots(1, 2, figsize=(W, 1.9))
    for s in ["PoS", "DPoS", "PBFT", "PoET2S"]:
        lat = [float(r["latency_ms"]) for r in sorted(rows, key=lambda r: int(r["N"])) if r["scheme"] == s]
        msg = [float(r["messages"]) for r in sorted(rows, key=lambda r: int(r["N"])) if r["scheme"] == s]
        lab = "PoET²S" if s == "PoET2S" else s
        axes[0].plot(ns, lat, "o-", ms=3, lw=1.2, color=col[s], mec="white", mew=0.5, label=lab)
        axes[1].plot(ns, msg, "o-", ms=3, lw=1.2, color=col[s], mec="white", mew=0.5, label=lab)
    for ax in axes:
        ax.set_xscale("log")
        ax.set_xticks(ns)
        ax.set_xticklabels([f"{n:,}" if n < 1000 else f"{n//1000}k" for n in ns])
        ax.set_xlabel("Network size N")
    axes[0].set_ylabel("Commit latency (ms)")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("Messages per block")
    axes[0].legend(frameon=False, loc="upper left", fontsize=6)
    fig.tight_layout(w_pad=0.8)
    save(fig, "fig11_scaling.png")


if __name__ == "__main__":
    main = load("main_per_seed.csv")
    print("seeds per scheme:", len(per_seed(main, "PoET2S", "latency_ms")))
    v = fig_validation()
    print("  validation slope %.3f" % v[2])
    fig_latency(main)
    fig_detection(main)
    fig_infiltration_baselines(main)
    fig_design_points(main)
    fig_pairs(main)
    fig_trajectory()
    fig_byzantine()
    fig_adaptive()
    fig_sensitivity()
    fig_scaling()
    fig_matched_fp()

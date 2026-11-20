"""Draws report/figures/er.png (ER diagram) and perf.png (latency + backtest, from bench/results/*.csv)."""
import csv, collections
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "figures"

# name: (col, row, layer, lines)   layer: C core, D derived, S service
T = {
 "competition": (0,0,"C",["PK competition_id","is_covered, is_big5","is_uefa_club"]),
 "club": (1,0,"C",["PK club_id","FK domestic_comp_id","is_stub"]),
 "player": (2,0,"C",["PK player_id","FK current_club_id","date_of_birth","pos_group (generated)"]),
 "game": (3,0,"C",["PK game_id","FK competition_id","FK home/away_club_id","season, date, goals"]),
 "appearance": (4,0,"C",["PK appearance_id","FK game_id, player_id","FK club_id, competition_id","minutes_played","UNIQUE(game,player)"]),
 "game_event": (5,0,"C",["PK game_event_id","FK game_id, club_id","type, minute","player(_in)_id (no FK)"]),
 "player_valuation": (0,1,"C",["PK (player_id, date)","FK player_id, club_id","market_value_eur"]),
 "player_season": (1,1,"D",["PK (player_id, season)","FK player_id, main_club_id","age, pos_group","league_minutes, onpitch_*"]),
 "player_season_metric": (2,1,"D",["PK (player_id, season,","   metric_code)","FK player_season (CASCADE)","FK metric_code; value"]),
 "metric (+metric_weight)": (3,1,"D",["PK metric_code","higher_is_better","min_minutes","weight: PK(pos_group,code)"]),
 "snapshot": (4,1,"D",["PK snapshot_id","name UNIQUE","as_of_date","built_at"]),
 "cohort_baseline": (5,1,"D",["PK (snapshot_id, pos_group,","   age, metric_code)","FK snapshot_id, metric_code","mean, std, n"]),
 "player_season_z": (0,2,"D",["PK (snapshot_id,player_id,","   season, metric_code)","FK snapshot, player_season,","   metric; z; age, pos_group*"]),
 "world_class_definition": (1,2,"D",["PK def_id","code UNIQUE","rule_type, thresholds"]),
 "world_class_label": (2,2,"D",["PK (snapshot_id,def_id,","   player_id)","FK snapshot, def, player","is_world_class"]),
 "app_user": (3,2,"S",["PK user_id","username UNIQUE","role CHECK scout|admin"]),
 "watchlist": (4,2,"S",["PK (user_id, player_id)","FK app_user, player","memo"]),
 "scouting_note": (5,2,"S",["PK note_id","FK user_id, player_id","rating 1..5, body"]),
 "recommendation_run": (0,3,"S",["PK run_id","FK user_id, snapshot_id,","   def_id","method, pos_group, params"]),
 "recommendation_item": (1,3,"S",["PK (run_id, rank)","FK run_id, player_id","score, wc_neighbors"]),
 "recommendation_evidence": (2,3,"S",["PK (run_id,player_id,","   neighbor,season)","FK item, neighbor_player_id","distance"]),
 "backtest_result": (3,3,"S",["PK (run_id,outcome_snap,k)","FK run_id, snapshot_id","hits, precision, recall"]),
}
EDGES = [("club","competition"),("player","club"),("game","competition"),("game","club"),
 ("appearance","game"),("appearance","player"),("game_event","game"),("player_valuation","player"),
 ("player_season","player"),("player_season_metric","player_season"),("player_season_metric","metric (+metric_weight)"),
 ("cohort_baseline","snapshot"),("player_season_z","snapshot"),("player_season_z","player_season"),
 ("world_class_label","snapshot"),("world_class_label","world_class_definition"),("world_class_label","player"),
 ("watchlist","app_user"),("watchlist","player"),("scouting_note","app_user"),("scouting_note","player"),
 ("recommendation_run","app_user"),("recommendation_run","snapshot"),("recommendation_run","world_class_definition"),
 ("recommendation_item","recommendation_run"),("recommendation_evidence","recommendation_item"),
 ("backtest_result","recommendation_run"),("backtest_result","snapshot")]
COL = {"C": "#dbe7f5", "D": "#dff0d8", "S": "#fbe5cf"}
EDGE = {"C": "#3b6ea5", "D": "#4a8f3a", "S": "#c77a24"}
W, H0, LH = 1.02, 0.25, 0.15


def er():
    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    ax.set_xlim(-0.05, 7.25); ax.set_ylim(-0.1, 4.7); ax.axis("off")
    pos = {}
    for n, (c, r, l, lines) in T.items():
        h = H0 + LH * len(lines) + 0.06
        pos[n] = (c * 1.2, 4.6 - r * 1.22 - h, h)
    def edge_pt(box, tx, ty):
        x, y, h = box; cx, cy = x + W / 2, y + h / 2
        dx, dy = tx - cx, ty - cy
        t = min((W / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
        return cx + dx * t, cy + dy * t
    for a, b in EDGES:
        ca = (pos[a][0] + W / 2, pos[a][1] + pos[a][2] / 2); cb = (pos[b][0] + W / 2, pos[b][1] + pos[b][2] / 2)
        p0 = edge_pt(pos[a], *cb); p1 = edge_pt(pos[b], *ca)
        ax.annotate("", xy=p1, xytext=p0, zorder=2,
                    arrowprops=dict(arrowstyle="-|>", color="#555555", lw=0.6, shrinkA=0, shrinkB=0, mutation_scale=5))
    for n, (c, r, l, lines) in T.items():
        x, y, h = pos[n]
        ax.add_patch(FancyBboxPatch((x, y), W, h, boxstyle="round,pad=0.0,rounding_size=0.03",
                                    fc=COL[l], ec=EDGE[l], lw=0.8, zorder=3))
        ax.text(x + 0.04, y + h - 0.04, n, fontsize=(4.0 if len(n) > 20 else 4.7), fontweight="bold", va="top", zorder=4)
        for i, t in enumerate(lines):
            ax.text(x + 0.04, y + h - H0 + 0.05 - i * LH, t, fontsize=4.1, va="top", zorder=4,
                    fontweight="bold" if t.startswith("PK") else "normal")
    ax.text(7.2, 0.55, "Core (raw, 3NF)", color=EDGE["C"], fontsize=6, ha="right", fontweight="bold")
    ax.text(7.2, 0.38, "Derived (snapshot-keyed)", color=EDGE["D"], fontsize=6, ha="right", fontweight="bold")
    ax.text(7.2, 0.21, "Service", color=EDGE["S"], fontsize=6, ha="right", fontweight="bold")
    ax.text(7.2, 0.04, "arrow = FK (child -> parent)", fontsize=5.2, ha="right")
    ax.text(7.2, 0.80, "* denormalized; game_lineup,\ntransfer omitted", fontsize=4.8, ha="right", va="bottom")
    fig.savefig(OUT / "er.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def perf():
    summ = list(csv.DictReader(open(ROOT / "bench/results/query_summary.csv")))
    bt = list(csv.DictReader(open(ROOT / "bench/results/backtest.csv")))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 2.35), gridspec_kw={"width_ratios": [1.15, 1]})
    qs = ["Q1", "Q2", "Q3"]; cfg = ["B1", "B2", "P"]
    colr = {"B1": "#9aa5b1", "B2": "#4c78a8", "P": "#e45756"}
    for i, c in enumerate(cfg):
        vals = [float(next(r for r in summ if r["query"] == q and r["config"] == c)["median_ms"]) for q in qs]
        xs = [j + (i - 1) * 0.27 for j in range(3)]
        a1.bar(xs, vals, 0.26, color=colr[c], label=c)
        for x, v in zip(xs, vals):
            a1.text(x, v * 1.12, f"{v:,.1f}" if v < 100 else f"{v:,.0f}", ha="center", fontsize=5.5)
    a1.set_yscale("log"); a1.set_ylim(0.1, 3e4); a1.set_xticks(range(3))
    a1.set_xticklabels(["Q1 season history", "Q2 cohort percentile", "Q3 k-NN (k=10)"], fontsize=6.5)
    a1.set_ylabel("median latency (ms, log)", fontsize=6.5); a1.tick_params(axis="y", labelsize=6)
    a1.legend(fontsize=6, ncol=3, loc="upper right"); a1.set_title("(a) Query latency", fontsize=7.5)
    agg = collections.defaultdict(list)
    for r in bt:
        if r["k"] == "20" and r["pos_group"] != "GK":
            agg[r["method"]].append(float(r["precision"]))
    ms = ["random", "market_value", "similarity", "hybrid"]
    vals = [sum(agg[m]) / len(agg[m]) for m in ms]
    a2.bar(range(4), vals, color=["#9aa5b1", "#f58518", "#4c78a8", "#54a24b"])
    for x, v in enumerate(vals):
        a2.text(x, v + 0.008, f"{v:.3f}", ha="center", fontsize=6.5)
    a2.set_xticks(range(4)); a2.set_xticklabels(["random", "market\nvalue", "similarity", "hybrid"], fontsize=6.5)
    a2.set_ylabel("precision@20 (DF/MF/FW cells)", fontsize=6.5); a2.tick_params(axis="y", labelsize=6)
    a2.set_ylim(0, 0.45); a2.set_title("(b) Backtest precision@20", fontsize=7.5)
    for a in (a1, a2):
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "perf.png", dpi=300); plt.close(fig)


def gui():
    """Compose the Tkinter career-explorer figure: search screen (left) + career screen (right)."""
    from PIL import Image
    a = Image.open(OUT / "gui_search.png").convert("RGB")
    b = Image.open(OUT / "gui_career.png").convert("RGB")
    gap = 40
    out = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), "white")
    out.paste(a, (0, 0)); out.paste(b, (a.width + gap, 0))
    out = out.resize((out.width // 2, out.height // 2), Image.LANCZOS)
    out.save(OUT / "gui.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True); er(); perf(); gui(); print("ok")

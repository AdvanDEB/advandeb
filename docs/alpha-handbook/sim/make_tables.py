"""Turn results.json into LaTeX tables and number macros for the alpha handbook.

Usage: python make_tables.py RESULTS_JSON OUT_DIR
"""
import json
import sys
from pathlib import Path

d = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)


def n(x, k=2):
    s = f"{x:.{k}f}"
    if s.startswith("-"):
        s = "−" + s[1:]
    return s.replace(".", "{,}")


def alab(a):
    return "$2/3$" if abs(a - 2 / 3) < 1e-6 else "$" + n(a, 2) + "$"


# ---------------------------------------------------------------- growth / storage table
rows = []
for r in d["growth_table"]:
    rows.append(" & ".join([
        alab(r["alpha"]), n(r["L200"]), n(r["L600"]), n(r["L1500"]),
        f"{r['dens_L1']:.0f}", f"{r['dens_L3']:.0f}",
        "$" + n(r["slope"], 3) + "$", "$" + n(r["slope_qss"], 3) + "$",
        "$" + n(r["alpha_naive"], 3) + "$", "$" + n(r["alpha_naive"] - r["alpha"], 3) + "$"]) + r" \\")
(out / "tab_growth.tex").write_text("\n".join(rows) + "\n")

# ---------------------------------------------------------------- starvation table
rows = []
for r in d["starvation_table"]:
    rows.append(" & ".join([alab(r["alpha"]), n(r["k_L1"], 4), n(r["k_L3"], 4),
                            "$" + n(r["slope"], 3) + "$", "$" + n(r["alpha"] - 1, 3) + "$"]) + r" \\")
(out / "tab_starv.tex").write_text("\n".join(rows) + "\n")

# ---------------------------------------------------------------- Monte Carlo table
rows = []
for r in d["monte_carlo"]:
    mis = abs(r["a_true"] - 2 / 3) > 1e-6
    tag = r["design"] + (r"$^{\ast}$" if mis else "")
    rows.append(" & ".join([
        tag, r["label"].replace("[E_E]", "$[E_E]$").replace(" x ", r" $\times$ ").replace("%", r"\%"), "$" + n(r["alpha_true"], 2) + "$",
        "$" + n(r["median"], 3) + "$", "$" + n(r["p10"], 2) + "$–$" + n(r["p90"], 2) + "$",
        "$" + n(r["rmse"], 3) + "$", f"{100 * r['frac_within_005']:.0f}~\\%"]) + r" \\")
(out / "tab_mc.tex").write_text("\n".join(rows) + "\n")

# ---------------------------------------------------------------- inline macros
g = {round(r["alpha"], 3): r for r in d["growth_table"]}
lo_ = g[0.667]
hi_ = g[1.0]
maxdiff = max(abs(hi_[k] - lo_[k]) / lo_[k] for k in ("L200", "L600", "L1500"))
pr = d["profile"]
ic = d["ic_convergence_L"]
mc = {(r["design"], round(r["alpha_true"], 2), round(r["a_true"], 3)): r for r in d["monte_carlo"]}
p = d["params"]
macros = {
    "GrowthMaxDiff": f"{100 * maxdiff:.0f}",
    "ProfLonlyMax": n(max(pr["L_only"]), 2),
    "CIlo": n(pr["ci_L_storage"][0], 2),
    "CIhi": n(pr["ci_L_storage"][1], 2),
    "AlphaBestProf": n(pr["alpha_best_L_storage"], 3),
    "ICtwoThirdsLo": n(min(ic["0.667_0.5"], ic["0.667_2.0"]), 2),
    "ICtwoThirdsHi": n(max(ic["0.667_0.5"], ic["0.667_2.0"]), 2),
    "IConeLo": n(min(ic["1.000_0.5"], ic["1.000_2.0"]), 2),
    "IConeHi": n(max(ic["1.000_0.5"], ic["1.000_2.0"]), 2),
    "NaiveBiasMin": n(min(abs(r["alpha_naive"] - r["alpha"]) for r in d["growth_table"]), 2),
    "NaiveBiasMax": n(max(abs(r["alpha_naive"] - r["alpha"]) for r in d["growth_table"]), 2),
    "MCreps": str(p["reps"]),
    "MCAsevenfiveMed": n(mc[("A", 0.75, 0.667)]["median"], 2),
    "MCAsevenfiveLo": n(mc[("A", 0.75, 0.667)]["p10"], 2),
    "MCAsevenfiveHi": n(mc[("A", 0.75, 0.667)]["p90"], 2),
    "MCArmse": n(max(mc[("A", 0.75, 0.667)]["rmse"], mc[("A", 0.9, 0.667)]["rmse"]), 2),
    "MCBrmse": n(max(mc[("B", 0.75, 0.667)]["rmse"], mc[("B", 0.9, 0.667)]["rmse"]), 2),
    "MCCrmse": n(max(mc[("C", 0.75, 0.667)]["rmse"], mc[("C", 0.9, 0.667)]["rmse"]), 2),
    "MCDrmse": n(max(mc[("D", 0.75, 0.667)]["rmse"], mc[("D", 0.9, 0.667)]["rmse"]), 2),
    "MCErmse": n(max(mc[("E", 0.75, 0.667)]["rmse"], mc[("E", 0.9, 0.667)]["rmse"]), 2),
    "MCFrmse": n(max(mc[("F", 0.75, 0.667)]["rmse"], mc[("F", 0.9, 0.667)]["rmse"]), 2),
    "MCCmisMed": n(mc[("C", 0.75, 0.72)]["median"], 3),
    "MCCokMed": n(mc[("C", 0.75, 0.667)]["median"], 3),
    "MCFmisMed": n(mc[("F", 0.75, 0.72)]["median"], 3),
    "MCFokMed": n(mc[("F", 0.75, 0.667)]["median"], 3),
}
(out / "numbers.tex").write_text("".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in macros.items()))
print("\n".join(f"{k} = {v}" for k, v in macros.items()))

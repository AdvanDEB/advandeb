"""Simulations and Monte Carlo design study behind the alpha handbook (tDEB).

Minimal transport-DEB (tDEB) as defined in the handbook (section 5.1):
    Delta p = beta * (E_T - k_E * E_E) * V^(alpha-1)
with the interface normalised so beta keeps conductance units (cm/d) for every alpha:
    A(V) = V^(2/3) * (V/V_ref)^(alpha-2/3)   ->   r(V) = (V/V_ref)^(alpha-2/3) / L

Usage:  python alpha_handbook_sim.py OUT_DIR [--reps N]
Writes OUT_DIR/results.json and vector figures OUT_DIR/fig_*.pdf (Croatian labels).
"""
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

P0 = dict(pAm=100.0, pM=20.0, EG=5000.0, bS=4.0, bR=1.0, bE=5.0, kE=0.01, a=2 / 3)
KAPPA = P0["bS"] / (P0["bS"] + P0["bR"])
L_INF = KAPPA * P0["pAm"] / P0["pM"]
V_REF = (0.5 * L_INF) ** 3
T_OBS = np.linspace(20, 1200, 25)
IDX8 = np.linspace(2, T_OBS.size - 1, 8).astype(int)
IDX16 = np.linspace(1, T_OBS.size - 1, 16).astype(int)
T_STARVE = (200.0, 600.0, 1200.0)          # start of starvation (L ~ 1, 2, 3 cm)
D_STARVE = np.array([0.0, 10.0, 20.0, 40.0])  # sampling days after food removal


def rhs(t, y, alpha, p, food):
    ET, EE, V, ER = y
    V = max(V, 1e-9)
    L = V ** (1 / 3)
    r = (V / V_REF) ** (alpha - 2 / 3) / L
    pA = p["pAm"] * food(t) * V ** (2 / 3) * (V / V_REF) ** (p["a"] - 2 / 3)
    pS = p["bS"] * ET * r
    pR = p["bR"] * ET * r
    pTE = p["bE"] * (ET - p["kE"] * EE) * r
    return [pA - pS - pR - pTE, pTE, (pS - p["pM"] * V) / p["EG"], pR]


def qss_state(L0, alpha, p, f=1.0, ee_mult=1.0):
    V = L0**3
    r = (V / V_REF) ** (alpha - 2 / 3) / L0
    pA = p["pAm"] * f * V ** (2 / 3) * (V / V_REF) ** (p["a"] - 2 / 3)
    ET = pA / ((p["bS"] + p["bR"]) * r)
    return [ET, ee_mult * ET / p["kE"], V, 0.0]


def run(alpha, p=P0, t_eval=None, t_end=None, food=lambda t: 1.0, y0=None, L0=0.3):
    t_eval = np.linspace(0, 1500, 601) if t_eval is None else np.asarray(t_eval, float)
    t_end = float(t_eval[-1]) if t_end is None else t_end
    y0 = qss_state(L0, alpha, p) if y0 is None else y0
    s = solve_ivp(rhs, (0, t_end), y0, args=(alpha, p, food), t_eval=t_eval,
                  method="LSODA", rtol=1e-7, atol=1e-9)
    if not s.success or s.y.shape[1] != len(t_eval):
        raise RuntimeError(s.message)
    return s.t, *s.y


# ------------------------------------------------------------------ synthetic data + fitting
DESIGNS = {
    "A": dict(label="samo L(t)", nE=0, sE=None, starve=False, sS=None),
    "B": dict(label="L(t) + 8 x [E_E] (10 %)", nE=8, sE=0.10, starve=False, sS=None),
    "C": dict(label="L(t) + 8 x [E_E] (25 %)", nE=8, sE=0.25, starve=False, sS=None),
    "D": dict(label="L(t) + 16 x [E_E] (25 %)", nE=16, sE=0.25, starve=False, sS=None),
    "E": dict(label="L(t) + gladovanje 3 x 4 (15 %)", nE=0, sE=None, starve=True, sS=0.15),
    "F": dict(label="L(t) + 8 x [E_E] (25 %) + gladovanje", nE=8, sE=0.25, starve=True, sS=0.15),
}
SIG_L = 0.02


def predict(p, alpha, design):
    out = {}
    _, ET, EE, V, _ = run(alpha, p=p, t_eval=T_OBS)
    out["L"] = V ** (1 / 3)
    if design["nE"]:
        idx = IDX8 if design["nE"] == 8 else IDX16
        out["E"] = (EE / V)[idx]
    if design["starve"]:
        series = []
        for ts in T_STARVE:
            te = ts + D_STARVE
            _, _, EEs, _, _ = run(alpha, p=p, t_eval=te, food=lambda t, ts=ts: 1.0 if t < ts else 0.0)
            series.append(EEs)
        out["S"] = np.concatenate(series)
    return out


def make_data(alpha, design, rng, p=P0):
    clean = predict(p, alpha, design)
    data = {"L": clean["L"] * (1 + SIG_L * rng.standard_normal(clean["L"].size))}
    if "E" in clean:
        data["E"] = clean["E"] * np.exp(design["sE"] * rng.standard_normal(clean["E"].size))
    if "S" in clean:
        data["S"] = clean["S"] * np.exp(design["sS"] * rng.standard_normal(clean["S"].size))
    return data


FIT_KEYS = ["pAm", "pM", "bS", "kE", "bE"]


def residuals(theta, design, data, a_assumed):
    p = dict(P0, a=a_assumed)
    for k, v in zip(FIT_KEYS, theta[:-1]):
        p[k] = float(np.exp(v))
    alpha = theta[-1]
    try:
        pr = predict(p, alpha, design)
    except Exception:
        n = data["L"].size + sum(data[k].size for k in ("E", "S") if k in data)
        return np.full(n, 1e3)
    res = [(pr["L"] - data["L"]) / (SIG_L * data["L"])]
    if "E" in data:
        res.append((np.log(np.maximum(pr["E"], 1e-12)) - np.log(data["E"])) / design["sE"])
    if "S" in data:
        res.append((np.log(np.maximum(pr["S"], 1e-12)) - np.log(data["S"])) / design["sS"])
    return np.concatenate(res)


def fit_one(task):
    key, alpha_true, seed, a_true = task
    design = DESIGNS[key]
    rng = np.random.default_rng(seed)
    data = make_data(alpha_true, design, rng, p=dict(P0, a=a_true))
    start = [np.log(P0[k]) + 0.2 * rng.standard_normal() for k in FIT_KEYS] + [0.80]
    lo = [np.log(P0[k]) - np.log(20) for k in FIT_KEYS] + [0.5]
    hi = [np.log(P0[k]) + np.log(20) for k in FIT_KEYS] + [1.2]
    best = None
    for a0 in (0.70, 0.95):          # multi-start in alpha; keep the lowest cost
        st = np.clip(start[:-1] + [a0], np.array(lo) + 1e-6, np.array(hi) - 1e-6)
        fit = least_squares(residuals, st, bounds=(lo, hi), args=(design, data, 2 / 3),
                            method="trf", diff_step=1e-3, xtol=1e-10, ftol=1e-10, max_nfev=800)
        if best is None or fit.cost < best.cost:
            best = fit
    return dict(design=key, alpha_true=alpha_true, a_true=a_true, seed=seed,
                alpha_hat=float(best.x[-1]), cost=float(best.cost), nfev=int(best.nfev))


# ------------------------------------------------------------------ deterministic analyses
def deterministic():
    res = {}
    alphas = [2 / 3, 0.75, 0.85, 1.0]
    rows = []
    curves = {}
    for a in alphas:
        t, ET, EE, V, ER = run(a)
        L = V ** (1 / 3)
        dens = EE / V
        m = (L > 1.0) & (L < 3.5)
        slope = float(np.polyfit(np.log(V[m]), np.log(dens[m]), 1)[0])
        rows.append(dict(alpha=a, L200=float(np.interp(200, t, L)), L600=float(np.interp(600, t, L)),
                         L1500=float(np.interp(1500, t, L)),
                         dens_L1=float(np.interp(1.0, L, dens)), dens_L3=float(np.interp(3.0, L, dens)),
                         slope=slope, slope_qss=2 / 3 - a, alpha_naive=2 / 3 - slope))
        curves[a] = (t, L, dens)
    res["growth_table"] = rows

    # starvation kinetics from QSS states at several sizes
    starv = []
    sizes = np.array([0.8, 1.0, 1.5, 2.0, 3.0])
    starv_curves = {}
    for a in alphas:
        ks = []
        for L0 in sizes:
            y0 = qss_state(L0, a, P0)
            t, ET, EE, V, ER = run(a, y0=y0, t_eval=np.linspace(0, 10, 201), food=lambda t: 0.0)
            m = (t > 1) & (t < 6)
            ks.append(-np.polyfit(t[m], np.log(EE[m]), 1)[0])
        ks = np.array(ks)
        sl = float(np.polyfit(np.log(sizes**3), np.log(ks), 1)[0])
        starv.append(dict(alpha=a, k_L1=float(ks[1]), k_L3=float(ks[4]), slope=sl))
        starv_curves[a] = (sizes, ks)
    res["starvation_table"] = starv

    # initial-condition sensitivity
    ic = {}
    for a in (2 / 3, 1.0):
        for mult in (0.5, 1.0, 2.0):
            y0 = qss_state(0.3, a, P0, ee_mult=mult)
            t, ET, EE, V, ER = run(a, y0=y0)
            L = V ** (1 / 3)
            ic[(a, mult)] = (L, EE / V)
    # when do 0.5x and 2x runs converge to within 5 % of the 1x run?
    conv = {}
    for a in (2 / 3, 1.0):
        Lr, Dr = ic[(a, 1.0)]
        for mult in (0.5, 2.0):
            L, D = ic[(a, mult)]
            Dref = np.interp(L, Lr, Dr)
            off = np.abs(D / Dref - 1)
            idx = np.where(off > 0.05)[0]
            conv[f"{a:.3f}_{mult}"] = float(L[idx[-1] + 1]) if idx.size and idx[-1] + 1 < L.size else float(L[0])
    res["ic_convergence_L"] = conv

    # profile likelihood (single synthetic data set, alpha_true = 0.75)
    rng = np.random.default_rng(1)
    _, _, EEt, Vt, _ = run(0.75, t_eval=T_OBS)
    L_obs = Vt ** (1 / 3) * (1 + 0.02 * rng.standard_normal(T_OBS.size))
    D_obs = (EEt / Vt)[IDX8] * (1 + 0.10 * rng.standard_normal(IDX8.size))
    grid = np.round(np.arange(0.50, 1.0001, 0.025), 3)

    def r1(th, a):
        p = dict(P0, pAm=np.exp(th[0]), pM=np.exp(th[1]), bS=np.exp(th[2]))
        _, _, _, V, _ = run(a, p=p, t_eval=T_OBS)
        return (V ** (1 / 3) - L_obs) / (0.02 * L_obs)

    def r2(th, a):
        p = dict(P0, pAm=np.exp(th[0]), pM=np.exp(th[1]), bS=np.exp(th[2]), kE=np.exp(th[3]))
        _, _, EE, V, _ = run(a, p=p, t_eval=T_OBS)
        return np.concatenate([(V ** (1 / 3) - L_obs) / (0.02 * L_obs),
                               ((EE / V)[IDX8] - D_obs) / (0.10 * D_obs)])

    def profile(fn, th0):
        best = {}
        th0 = np.array(th0, float)
        lo, hi = th0 - np.log(20), th0 + np.log(20)   # same box as the Monte Carlo fits
        for order in (list(grid), list(grid[::-1])):
            th = th0.copy()
            for a in order:
                for st in (th, th0):
                    st = np.clip(st, lo + 1e-6, hi - 1e-6)
                    f = least_squares(fn, st, args=(a,), method="trf", bounds=(lo, hi), diff_step=1e-3,
                                      xtol=1e-10, ftol=1e-10, max_nfev=300)
                    c = float(np.sum(f.fun**2))
                    if a not in best or c < best[a][0]:
                        best[a] = (c, f.x)
                th = best[a][1]
        c = np.array([best[a][0] for a in grid])
        return c - c.min()

    t0 = time.time()
    prof1 = profile(r1, np.log([P0["pAm"], P0["pM"], P0["bS"]]))
    print(f"  profile L(t): {time.time()-t0:.0f}s", flush=True)
    prof2 = profile(r2, np.log([P0["pAm"], P0["pM"], P0["bS"], P0["kE"]]))
    print(f"  profile L(t)+[E_E]: {time.time()-t0:.0f}s", flush=True)

    def ci(prof):
        inside = grid[prof < 3.84]
        # linear interpolation of the 3.84 crossing on both sides
        i_lo, i_hi = np.where(prof < 3.84)[0][[0, -1]]
        lo = grid[i_lo] if i_lo == 0 else np.interp(3.84, [prof[i_lo], prof[i_lo - 1]], [grid[i_lo], grid[i_lo - 1]])
        hi = grid[i_hi] if i_hi == grid.size - 1 else np.interp(3.84, [prof[i_hi], prof[i_hi + 1]], [grid[i_hi], grid[i_hi + 1]])
        return float(lo), float(hi), bool(i_lo == 0), bool(i_hi == grid.size - 1)

    res["profile"] = dict(grid=grid.tolist(), L_only=prof1.tolist(), L_storage=prof2.tolist(),
                          ci_L_only=ci(prof1), ci_L_storage=ci(prof2),
                          alpha_best_L_storage=float(grid[np.argmin(prof2)]))
    return res, curves, starv_curves, ic


# ------------------------------------------------------------------ figures
COL = {2 / 3: "#2a6fdb", 0.75: "#1b9e77", 0.85: "#d95f02", 1.0: "#c51b7d"}
LBL = {2 / 3: "2/3", 0.75: "0,75", 0.85: "0,85", 1.0: "1"}


def figures(out, det, curves, starv_curves, ic, mc):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.formatter.use_locale": False,
                         "pdf.fonttype": 42})

    def comma(ax):
        from matplotlib.ticker import FuncFormatter
        f = FuncFormatter(lambda x, _: f"{x:g}".replace(".", ","))
        ax.xaxis.set_major_formatter(f)
        ax.yaxis.set_major_formatter(f)

    # Fig: growth + storage density
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.9))
    for a, (t, L, dens) in curves.items():
        ax[0].plot(t, L, color=COL[a], lw=1.6, label=f"α = {LBL[a]}")
        ax[1].plot(L, dens, color=COL[a], lw=1.6)
    ax[0].set(xlabel="vrijeme (d)", ylabel="strukturna duljina L (cm)", title="Rast pri f = 1")
    ax[0].legend(frameon=False, fontsize=8)
    ax[1].set(xlabel="strukturna duljina L (cm)", ylabel=r"$[E_E]$ (J/cm³)", title="Gustoća spremišta",
              xlim=(0.5, 3.4), ylim=(800, 4500))
    for a_ in ax:
        comma(a_)
    fig.tight_layout()
    fig.savefig(out / "fig_rast_spremiste.pdf")
    plt.close(fig)

    # Fig: profile + starvation
    pr = det["profile"]
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.9))
    g = np.array(pr["grid"])
    ax[0].plot(g, pr["L_only"], "o-", ms=3.5, color="#555", label=r"samo $L(t)$")
    ax[0].plot(g, pr["L_storage"], "s-", ms=3.5, color="#c51b7d", label=r"$L(t)$ + 8 točaka $[E_E]$")
    ax[0].axhline(3.84, ls="--", lw=0.8, color="#999")
    ax[0].text(0.605, 5.0, "prag 95 %", fontsize=7.5, color="#777")
    ax[0].axvline(0.75, ls=":", lw=1, color="#1b9e77")
    ax[0].set(xlabel="α (fiksiran, ostalo refitano)", ylabel="Δχ²", title="Profil vjerodostojnosti (istina 0,75)",
              ylim=(-1, 40))
    ax[0].legend(frameon=False, fontsize=8)
    for a, (sz, ks) in starv_curves.items():
        ax[1].loglog(sz**3, ks, "o-", ms=3.5, color=COL[a], label=f"α = {LBL[a]}")
    ax[1].set(xlabel="strukturni volumen V (cm³)", ylabel="specifična brzina pražnjenja (1/d)",
              title="Gladovanje: nagib = α − 1")
    ax[1].legend(frameon=False, fontsize=7.5)
    comma(ax[0])
    fig.tight_layout()
    fig.savefig(out / "fig_profil_gladovanje.pdf")
    plt.close(fig)

    # Fig: initial conditions
    fig, ax = plt.subplots(1, 1, figsize=(4.6, 2.9))
    for (a, mult), (L, D) in ic.items():
        ls = {0.5: ":", 1.0: "-", 2.0: "--"}[mult]
        ax.plot(L, D, ls=ls, color=COL[a], lw=1.4,
                label=f"α = {LBL[a]}, " + r"$E_E(0)$" + f" = {str(mult).replace('.', ',')}× ravnoteže")
    ax.set(xlabel="strukturna duljina L (cm)", ylabel=r"$[E_E]$ (J/cm³)", xlim=(0.3, 3.4), ylim=(500, 9000),
           title="Osjetljivost na početne uvjete")
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=6.8, ncol=1)
    comma(ax)
    fig.tight_layout()
    fig.savefig(out / "fig_pocetni_uvjeti.pdf")
    plt.close(fig)

    # Fig: Monte Carlo
    if mc:
        fig, ax = plt.subplots(1, 1, figsize=(7.2, 3.3))
        keys = list(DESIGNS)
        for j, at in enumerate((0.75, 0.90)):
            for i, k in enumerate(keys):
                vals = [r["alpha_hat"] for r in mc if r["design"] == k and r["alpha_true"] == at and r["a_true"] == 2 / 3]
                x = i + (j - 0.5) * 0.32
                jit = np.random.default_rng(i * 10 + j).uniform(-0.07, 0.07, len(vals))
                c = "#1b9e77" if at == 0.75 else "#d95f02"
                ax.scatter(x + jit, vals, s=9, color=c, alpha=0.65, lw=0,
                           label=f"istinski α = {str(at).replace('.', ',')}" if i == 0 else None)
                if vals:
                    q = np.percentile(vals, [10, 50, 90])
                    ax.plot([x - 0.12, x + 0.12], [q[1]] * 2, color="k", lw=1.2)
                    ax.plot([x, x], [q[0], q[2]], color="k", lw=0.8)
            ax.axhline(at, color="#1b9e77" if at == 0.75 else "#d95f02", ls=":", lw=1)
        ax.set_xticks(range(len(keys)))
        short = {"A": "samo L(t)", "B": "+8 [E_E]\n10 %", "C": "+8 [E_E]\n25 %", "D": "+16 [E_E]\n25 %",
                 "E": "+gladovanje", "F": "+8 [E_E] 25 %\n+gladovanje"}
        ticks = [f"{k}\n" + short[k].replace("[E_E]", r"$[E_E]$").replace("L(t)", r"$L(t)$") for k in keys]
        ax.set_xticklabels(ticks, fontsize=7.2)
        ax.set(ylabel="procijenjeni α", ylim=(0.48, 1.22))
        ax.set_title("Koliko dizajn podataka otkriva α (Monte Carlo)", pad=22)
        ax.legend(frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
        comma(ax)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FixedFormatter(ticks))
        fig.tight_layout()
        fig.savefig(out / "fig_monte_carlo.pdf")
        plt.close(fig)

    # Fig: atlas of alpha-relevant exponents from literature
    rows = [
        # label, centre, lo, hi, kind
        ("Euklidski izomorf, samo vanjska površina (DEB)", 2 / 3, None, None, "t"),
        ("Banavar i sur. 2010: brzina toka neovisna o veličini", 2 / 3, None, None, "t"),
        (r"Banavar i sur. 2010: brzina toka $\propto M^{1/12}$", 0.75, None, None, "t"),
        ("WBE 1997/1999: gornja granica fraktalne mreže", 0.75, None, None, "t"),
        ("Savage i sur. 2008: konačna veličina, sisavci", 0.81, None, None, "t"),
        ("Savage i sur. 2008: samo Poiseuilleov tok (→ 1)", 0.93, 0.86, 1.0, "t"),
        ("Kooijman 2014: V1-morf, akceleracija tipa M", 1.0, None, None, "t"),
        ("Okie 2013: spektar površinskih strategija", 0.8, 0.55, 1.1, "t"),
        ("Pluća sisavaca: alveolarna/kapilarna površina", 0.92, 0.87, 0.97, "e"),
        (r"Pluća sisavaca: difuzijski kapacitet $D_{LO_2}$", 0.97, 0.95, 0.99, "e"),
        (r"Mišić sisavaca: $\dot V_{O_2\max}$ (34 vrste)", 0.872, 0.843, 0.901, "e"),
        ("Mišić sisavaca: volumen kapilara (11 vrsta)", 0.984, 0.909, 1.056, "e"),
        ("Mišić sisavaca: volumen mitohondrija (11 vrsta)", 0.956, 0.846, 1.066, "e"),
        ("Škrge slatkovodnih riba (raspon, sredina 0,76)", 0.76, 0.36, 1.13, "e"),
        ("Šaran 0,2–2250 g: škrge", 0.794, None, None, "e"),
        ("Šaran: površina tijela", 0.62, 0.52, 0.72, "e"),
        ("Šaran postlarva (< 0,2 g): škrge", 1.222, None, None, "e"),
        (r"Obrtaj izotopa C/N $\propto M^{-0{,}19}$ (izvedeno)", 0.81, None, None, "i"),
        (r"$^{13}$C u krvi ptica $\propto M^{-1/4}$ (izvedeno)", 0.75, None, None, "i"),
        (r"Mrežnica: $\alpha_{2D}=D/2$, $D$ = 1,63–1,71 (izvedeno, P6)", 0.835, 0.815, 0.855, "g"),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 5.7))
    ax.axvspan(2 / 3, 1.0, color="#eee", zorder=0)
    colk = {"t": "#2a6fdb", "e": "#c51b7d", "i": "#1b9e77", "g": "#d95f02"}
    for i, (lab, c, lo, hi, kd) in enumerate(rows[::-1]):
        if lo is not None:
            ax.plot([lo, hi], [i, i], color=colk[kd], lw=2.2, alpha=0.45, solid_capstyle="round")
        ax.plot([c], [i], "o", color=colk[kd], ms=5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=7.4)
    ax.set_xlim(0.3, 1.3)
    ax.axvline(2 / 3, color="#999", lw=0.6)
    ax.axvline(1.0, color="#999", lw=0.6)
    ax.set_xlabel(r"eksponent površine izmjene $\alpha$  ($A \propto V^{\alpha}$)")
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=colk[k], label=l) for k, l in
                       (("t", "teorija"), ("e", "mjerenje (morfometrija)"), ("i", r"kinetika, izvedeno uz $V \propto M$"),
                        ("g", "geometrija, izvedeno (P6)"))],
              frameon=False, fontsize=7.5, loc="lower right")
    y_pl = [r[0] for r in rows[::-1]].index("Šaran postlarva (< 0,2 g): škrge")
    ax.text(1.29, y_pl, "prelarva: 7,07 →", fontsize=6.8, color="#c51b7d", va="center", ha="right")
    from matplotlib.ticker import FuncFormatter
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}".replace(".", ",")))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "fig_atlas.pdf")
    plt.close(fig)


# ------------------------------------------------------------------ main
def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else 16
    t0 = time.time()
    det, curves, starv_curves, ic = deterministic()
    print(f"deterministic done in {time.time()-t0:.0f}s", flush=True)

    tasks = [(k, at, 1000 + 97 * i + int(at * 100), 2 / 3)
             for k in DESIGNS for at in (0.75, 0.90) for i in range(reps)]
    # misspecification: true assimilation exponent 0.72, model assumes 2/3
    tasks += [(k, 0.75, 5000 + i, 0.72) for k in ("C", "F") for i in range(reps)]
    raw = out / "monte_carlo_raw.json"
    if "--reuse-mc" in sys.argv and raw.exists():
        mc = json.loads(raw.read_text())
    else:
        with Pool(8) as pool:
            mc = pool.map(fit_one, tasks, chunksize=1)
    print(f"monte carlo ({len(tasks)} fits) done in {time.time()-t0:.0f}s", flush=True)

    summ = []
    for k in DESIGNS:
        for at, atrue in ((0.75, 2 / 3), (0.90, 2 / 3), (0.75, 0.72)):
            v = np.array([r["alpha_hat"] for r in mc if r["design"] == k and r["alpha_true"] == at
                          and abs(r["a_true"] - atrue) < 1e-9])
            if v.size:
                summ.append(dict(design=k, label=DESIGNS[k]["label"], alpha_true=at, a_true=atrue, n=int(v.size),
                                 median=float(np.median(v)), mean=float(v.mean()), sd=float(v.std(ddof=1)),
                                 p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90)),
                                 rmse=float(np.sqrt(np.mean((v - at) ** 2))),
                                 frac_within_005=float(np.mean(np.abs(v - at) <= 0.05)),
                                 frac_at_bound=float(np.mean((v < 0.51) | (v > 1.19)))))
    det["monte_carlo"] = summ
    det["params"] = dict(P0, kappa=KAPPA, L_inf=L_INF, V_ref=V_REF, sig_L=SIG_L, reps=reps)
    (out / "results.json").write_text(json.dumps(det, indent=1, ensure_ascii=False))
    (out / "monte_carlo_raw.json").write_text(json.dumps(mc, indent=0))
    figures(out, det, curves, starv_curves, ic, mc)
    print(f"all done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

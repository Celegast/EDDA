"""
Chart generation for exploration statistics.
Produces both static PNG (matplotlib/seaborn) and interactive HTML (plotly).

When out_path is None, static functions return a base64 PNG string and
interactive functions return a go.Figure — used by the dashboard builder.
"""

import base64
import io
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns


plt.rcParams.update({
    "figure.facecolor": "#0a0a1a",
    "axes.facecolor":   "#0f0f2a",
    "axes.edgecolor":   "#333355",
    "axes.labelcolor":  "white",
    "xtick.color":      "white",
    "ytick.color":      "white",
    "text.color":       "white",
    "grid.color":       "#222244",
    "grid.linestyle":   "--",
    "grid.alpha":       0.4,
})

_PALETTE = sns.color_palette("viridis", 20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_static(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved: {path}")


def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _fmt_credits(n: float) -> str:
    if n >= 1e9:
        return f"{n/1e9:.1f} BCr"
    if n >= 1e6:
        return f"{n/1e6:.1f} MCr"
    if n >= 1e3:
        return f"{n/1e3:.0f} KCr"
    return str(int(n))


def _write_interactive(fig: go.Figure, out_path: Path) -> None:
    fig.write_html(str(out_path))
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# Body type pie / bar
# ---------------------------------------------------------------------------

def plot_body_types_static(df: pd.DataFrame,
                           out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    top = df.head(12)
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(top["subtype"][::-1], top["count"][::-1],
                   color=sns.color_palette("viridis", len(top)))
    ax.set_xlabel("Count")
    ax.set_title("Planet Types Scanned")
    ax.grid(axis="x")
    for bar, val in zip(bars, top["count"][::-1]):
        ax.text(bar.get_width() + top["count"].max() * 0.01,
                bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=8)
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_body_types_interactive(df: pd.DataFrame,
                                out_path: Path | None = None) -> go.Figure | None:
    if df.empty:
        return None
    fig = px.bar(df.head(15), x="count", y="subtype", orientation="h",
                 title="Planet Types Scanned", color="count",
                 color_continuous_scale="Viridis")
    fig.update_layout(paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
                      font_color="white", yaxis=dict(autorange="reversed"))
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Star class bar
# ---------------------------------------------------------------------------

def plot_star_classes_static(df: pd.DataFrame,
                             out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = sns.color_palette("magma", len(df))
    ax.bar(df["star_class"], df["count"], color=colors)
    ax.set_xlabel("Spectral class")
    ax.set_ylabel("Systems")
    ax.set_title("Primary Star Classes Visited")
    ax.grid(axis="y")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Exploration income over time
# ---------------------------------------------------------------------------

def plot_exploration_income_static(df: pd.DataFrame,
                                   out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.bar(df["date"], df["credits"], color="#4488cc", width=0.8)
    ax1.set_ylabel("Credits per day")
    ax1.set_title("Exploration Income")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_credits(x)))
    ax1.grid(axis="y")

    ax2.plot(df["date"], df["cumulative"], color="#88ddff", linewidth=1.5)
    ax2.fill_between(df["date"], df["cumulative"], alpha=0.2, color="#88ddff")
    ax2.set_ylabel("Cumulative credits")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_credits(x)))
    ax2.grid(axis="y")

    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_exploration_income_interactive(df: pd.DataFrame,
                                        out_path: Path | None = None) -> go.Figure | None:
    if df.empty:
        return None
    fig = go.Figure()
    fig.add_bar(x=df["date"], y=df["credits"], name="Per day",
                marker_color="#4488cc")
    fig.add_scatter(x=df["date"], y=df["cumulative"], name="Cumulative",
                    line=dict(color="#88ddff", width=2), yaxis="y2")
    fig.update_layout(
        title="Exploration Income Over Time",
        yaxis=dict(title="Credits / day"),
        yaxis2=dict(title="Cumulative", overlaying="y", side="right"),
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a", font_color="white",
        legend=dict(bgcolor="#111133"),
    )
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Organic (bio) income over time
# ---------------------------------------------------------------------------

def plot_organic_income_static(df: pd.DataFrame,
                               out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.bar(df["date"], df["credits"], color="#44cc88", width=0.8)
    ax1.set_ylabel("Credits per day")
    ax1.set_title("Exobiology Income")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_credits(x)))
    ax1.grid(axis="y")

    ax2.plot(df["date"], df["cumulative"], color="#aaffcc", linewidth=1.5)
    ax2.fill_between(df["date"], df["cumulative"], alpha=0.2, color="#aaffcc")
    ax2.set_ylabel("Cumulative credits")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: _fmt_credits(x)))
    ax2.grid(axis="y")

    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Jump distance histogram
# ---------------------------------------------------------------------------

def plot_jump_histogram_static(series: pd.Series,
                               out_path: Path | None = None) -> str | None:
    if series.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(series, bins=80, color="#5599ff", edgecolor="none", alpha=0.85)
    ax.set_xlabel("Jump distance (ly)")
    ax.set_ylabel("Count")
    ax.set_title("FSD Jump Distance Distribution")
    ax.grid(axis="y")
    ax.axvline(series.mean(), color="orange", linestyle="--", linewidth=1.2,
               label=f"Mean: {series.mean():.1f} ly")
    ax.axvline(series.max(), color="red", linestyle="--", linewidth=1.2,
               label=f"Max: {series.max():.1f} ly")
    ax.legend()
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Top species bar
# ---------------------------------------------------------------------------

def plot_top_species_static(df: pd.DataFrame,
                            out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, max(5, len(df) * 0.4)))
    colors = sns.color_palette("YlGn", len(df))
    ax.barh(df["species"][::-1], df["scans"][::-1], color=colors[::-1])
    ax.set_xlabel("Completed scans")
    ax.set_title("Top Organisms Scanned")
    ax.grid(axis="x")
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Species × planet type heatmap
# ---------------------------------------------------------------------------

def plot_species_planet_heatmap_static(df: pd.DataFrame,
                                       out_path: Path | None = None) -> str | None:
    if df.empty:
        return None
    pivot = df.pivot_table(index="genus", columns="planet_type",
                           values="scan_count", fill_value=0)
    if pivot.empty:
        return None
    fig, ax = plt.subplots(figsize=(max(10, len(pivot.columns) * 1.2),
                                    max(4, len(pivot) * 0.9)))
    sns.heatmap(pivot.astype(int), ax=ax, cmap="YlGn", linewidths=0.3,
                linecolor="#0f0f2a", annot=True, fmt="d",
                cbar_kws={"label": "Scans"},
                yticklabels=True)
    ax.set_title("Genus × Planet Type Heatmap")
    ax.set_xlabel("Planet type")
    ax.set_ylabel("Genus")
    plt.setp(ax.get_xticklabels(), rotation=40, ha="right", fontsize=7)
    plt.setp(ax.get_yticklabels(), rotation=0, fontsize=7)
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_species_planet_heatmap_interactive(df: pd.DataFrame,
                                            out_path: Path | None = None) -> go.Figure | None:
    if df.empty:
        return None
    pivot = df.pivot_table(index="genus", columns="planet_type",
                           values="scan_count", fill_value=0)
    if pivot.empty:
        return None

    n_rows, n_cols = pivot.shape
    y_labels = list(pivot.index) + ["Total"]
    x_labels = list(pivot.columns) + ["Total"]

    z_full = np.zeros((n_rows + 1, n_cols + 1), dtype=int)
    z_full[:n_rows, :n_cols] = pivot.values
    z_full[:n_rows, n_cols] = pivot.sum(axis=1).values
    z_full[n_rows, :n_cols] = pivot.sum(axis=0).values
    z_full[n_rows, n_cols] = int(pivot.values.sum())

    # Data cells only (NaN out the Total row/column)
    z_data = z_full.astype(float)
    z_data[n_rows, :] = np.nan
    z_data[:, n_cols] = np.nan

    # Total cells only (NaN out the data cells)
    z_totals = np.full((n_rows + 1, n_cols + 1), np.nan)
    z_totals[n_rows, :] = z_full[n_rows, :]
    z_totals[:, n_cols] = z_full[:, n_cols]

    data_max = int(pivot.values.max())

    # Per-cell text colour: white on dark cells, near-black on light cells
    annotations = []
    for i, y_lbl in enumerate(y_labels):
        for j, x_lbl in enumerate(x_labels):
            val = z_full[i, j]
            is_total = (i == n_rows or j == n_cols)
            color = "white" if (is_total or val > data_max * 0.5) else "#111111"
            annotations.append(dict(
                x=x_lbl, y=y_lbl, text=str(val),
                showarrow=False, font=dict(size=13, color=color),
                xref="x", yref="y",
            ))

    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        z=z_data, x=x_labels, y=y_labels,
        customdata=z_full,
        colorscale="YlGn", zmin=0, zmax=data_max,
        colorbar=dict(title=dict(text="Scans", font=dict(color="white")),
                      tickfont=dict(color="white")),
        hovertemplate="Genus: %{y}<br>Planet: %{x}<br>Scans: %{customdata}<extra></extra>",
    ))
    fig.add_trace(go.Heatmap(
        z=z_totals, x=x_labels, y=y_labels,
        colorscale=[[0, "#3a3a5a"], [1, "#3a3a5a"]],
        showscale=False,
        hoverinfo="skip",
    ))

    fig.update_layout(
        title="Genus × Planet Type Heatmap",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a", font_color="white",
        height=max(400, (n_rows + 1) * 35 + 150),
        annotations=annotations,
    )
    fig.update_yaxes(autorange="reversed", tickmode="array",
                     tickvals=list(range(n_rows + 1)), ticktext=y_labels)

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Body value charts
# ---------------------------------------------------------------------------

def plot_body_values_by_type_static(df: pd.DataFrame,
                                    out_path: Path | None = None) -> str | None:
    """Stacked bar: total estimated value per planet type, split by discovery/mapping status."""
    if df.empty:
        return None

    df = df.copy()
    df["category"] = "Scanned"
    df.loc[df["first_discovered"] == 1, "category"] = "First discovered"
    df.loc[df["was_mapped"] == 1, "category"] = "Mapped"
    df.loc[(df["was_mapped"] == 1) & (df["first_mapped"] == 1), "category"] = "First mapped"
    df.loc[
        (df["first_discovered"] == 1) & (df["was_mapped"] == 1) & (df["first_mapped"] == 1),
        "category"
    ] = "First disc. + first mapped"

    grp = (df.groupby(["planet_class", "category"])["estimated_value"]
             .sum()
             .reset_index()
             .sort_values("estimated_value", ascending=False))

    top_types = df.groupby("planet_class")["estimated_value"].sum().nlargest(12).index
    grp = grp[grp["planet_class"].isin(top_types)]

    cat_order = ["Scanned", "First discovered", "Mapped",
                 "First mapped", "First disc. + first mapped"]
    cat_colors = {
        "Scanned":                    "#334466",
        "First discovered":           "#4488cc",
        "Mapped":                     "#44aa66",
        "First mapped":               "#ddaa22",
        "First disc. + first mapped": "#ff6622",
    }

    pivot = (grp.pivot_table(index="planet_class", columns="category",
                             values="estimated_value", fill_value=0)
               .reindex(columns=[c for c in cat_order if c in grp["category"].unique()]))
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=True).index]

    fig, ax = plt.subplots(figsize=(12, max(5, len(pivot) * 0.5)))
    left = np.zeros(len(pivot))
    for cat in pivot.columns:
        vals = pivot[cat].to_numpy() / 1e9
        ax.barh(pivot.index, vals, left=left, color=cat_colors.get(cat, "#888"),
                label=cat, height=0.7)
        left += vals

    ax.set_xlabel("Estimated value (B Cr)")
    ax.set_title("Body Exploration Value by Planet Type")
    ax.legend(loc="lower right", fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f} BCr"))
    ax.grid(axis="x")
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_body_values_by_type_interactive(df: pd.DataFrame,
                                         out_path: Path | None = None) -> go.Figure | None:
    if df.empty:
        return None
    grp = (df.groupby("planet_class")
             .agg(total_value=("estimated_value", "sum"),
                  body_count=("body_id", "count"),
                  first_disc=("first_discovered", "sum"),
                  mapped=("was_mapped", "sum"),
                  first_mapped=("first_mapped", "sum"))
             .reset_index()
             .sort_values("total_value", ascending=False)
             .head(15))
    grp["avg_value"] = grp["total_value"] / grp["body_count"]

    fig = px.bar(grp, x="total_value", y="planet_class", orientation="h",
                 color="avg_value", color_continuous_scale="Plasma",
                 hover_data=["body_count", "first_disc", "mapped", "first_mapped"],
                 title="Body Exploration Value by Planet Type",
                 labels={"total_value": "Total estimated (Cr)",
                         "planet_class": "Planet type",
                         "avg_value": "Avg per body (Cr)"})
    fig.update_layout(paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
                      font_color="white", yaxis=dict(autorange="reversed"))
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


def plot_body_value_histogram_static(df: pd.DataFrame,
                                     out_path: Path | None = None) -> str | None:
    """Distribution of per-body estimated values (log scale)."""
    if df.empty:
        return None
    vals = df.loc[df["estimated_value"] > 0, "estimated_value"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(np.log10(vals), bins=60, color="#5599ff", edgecolor="none", alpha=0.85)
    ax.set_xlabel("log₁₀(estimated value in Cr)")
    ax.set_ylabel("Bodies")
    ax.set_title("Distribution of Body Exploration Values")
    ax.grid(axis="y")
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Organic value charts
# ---------------------------------------------------------------------------

def plot_organic_value_by_species_static(df: pd.DataFrame,
                                         out_path: Path | None = None,
                                         top_n: int = 25) -> str | None:
    """Horizontal bar: total estimated organic income per species."""
    if df.empty:
        return None

    grp = (df.groupby("species")
             .agg(total=("estimated_payout", "sum"),
                  scans=("species", "count"),
                  first_logs=("is_first_log", "sum"))
             .reset_index()
             .sort_values("total", ascending=False)
             .head(top_n))

    fig, ax = plt.subplots(figsize=(11, max(5, len(grp) * 0.38)))
    colors = sns.color_palette("YlGn_r", len(grp))
    ax.barh(grp["species"][::-1], grp["total"][::-1] / 1e6,
            color=colors[::-1])
    ax.set_xlabel("Estimated value (M Cr)")
    ax.set_title(f"Top {top_n} Organic Species by Total Estimated Income")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f} MCr"))
    ax.grid(axis="x")
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_organic_value_by_species_interactive(df: pd.DataFrame,
                                               out_path: Path | None = None,
                                               top_n: int = 40) -> go.Figure | None:
    if df.empty:
        return None
    grp = (df.groupby("species")
             .agg(total_estimated=("estimated_payout", "sum"),
                  scans=("species", "count"),
                  first_logs=("is_first_log", "sum"),
                  genus=("genus", "first"))
             .reset_index()
             .sort_values("total_estimated", ascending=False)
             .head(top_n))

    fig = px.bar(grp, x="total_estimated", y="species", orientation="h",
                 color="genus", hover_data=["scans", "first_logs"],
                 title=f"Organic Income by Species (top {top_n})",
                 labels={"total_estimated": "Estimated income (Cr)",
                         "species": "Species", "genus": "Genus"})
    fig.update_layout(paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
                      font_color="white", yaxis=dict(autorange="reversed"),
                      height=max(500, top_n * 22))
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


def plot_organic_value_by_planet_type_static(df: pd.DataFrame,
                                              out_path: Path | None = None) -> str | None:
    """How much organic income comes from each planet type."""
    if df.empty:
        return None
    grp = (df.groupby("planet_class")["estimated_payout"]
             .sum().reset_index()
             .sort_values("estimated_payout", ascending=True))
    fig, ax = plt.subplots(figsize=(10, max(4, len(grp) * 0.4)))
    ax.barh(grp["planet_class"], grp["estimated_payout"] / 1e9,
            color=sns.color_palette("YlGn", len(grp)))
    ax.set_xlabel("Estimated value (B Cr)")
    ax.set_title("Organic Income by Host Planet Type")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f} BCr"))
    ax.grid(axis="x")
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Valuable-regions charts
# ---------------------------------------------------------------------------

def plot_body_rate_vs_z_static(df: pd.DataFrame,
                                out_path: Path | None = None) -> str | None:
    """
    Line chart: terraformable / ELW / WW / bio rates vs galactic Y position.

    Y ~ 0 = galactic plane (higher metallicity).
    df must have columns: y_bin_centre, systems, terra_rate, elw_rate,
                          ww_rate, bio_rate.
    """
    if df.empty:
        return None

    fig, ax = plt.subplots(figsize=(12, 5))

    metrics = [
        ("terra_rate", "#ffaa33", "Terraformable"),
        ("bio_rate",   "#44dd88", "Bio signals"),
        ("ww_rate",    "#4488ff", "Water Worlds"),
        ("elw_rate",   "#ff4455", "Earth-likes"),
    ]
    for col, color, label in metrics:
        if col in df.columns:
            ax.plot(df["y_bin_centre"], df[col], color=color, lw=2, label=label)

    ax.axvline(0, color="white", lw=0.8, linestyle=":", alpha=0.5,
               label="Galactic plane (Y=0)")
    ax.set_xlabel("Galactic Y (ly above/below galactic plane)")
    ax.set_ylabel("Rate (bodies per visited system)")
    ax.set_title("Valuable Body Rates vs Galactic Height")
    ax.legend(framealpha=0.25, labelcolor="white")
    ax.grid(True)

    # Secondary axis: system count per bin
    ax2 = ax.twinx()
    ax2.fill_between(df["y_bin_centre"], df["systems"], alpha=0.12,
                     color="#aaaacc", step="mid", label="Systems visited")
    ax2.set_ylabel("Systems visited", color="#aaaacc")
    ax2.tick_params(colors="#aaaacc")
    ax2.set_ylim(bottom=0)

    fig.tight_layout()
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_body_rate_vs_z_interactive(df: pd.DataFrame,
                                    out_path: Path | None = None) -> go.Figure | None:
    """Interactive Plotly version of the galactic-height rate chart."""
    if df.empty:
        return None

    fig = go.Figure()
    metrics = [
        ("terra_rate", "#ffaa33", "Terraformable"),
        ("bio_rate",   "#44dd88", "Bio signals"),
        ("ww_rate",    "#4488ff", "Water Worlds"),
        ("elw_rate",   "#ff4455", "Earth-likes"),
    ]
    # System-count background bar (secondary y)
    fig.add_trace(go.Bar(
        x=df["y_bin_centre"], y=df["systems"],
        name="Systems visited", marker_color="rgba(170,170,200,0.15)",
        yaxis="y2", hovertemplate="Y=%{x:.0f} ly<br>Systems: %{y}<extra></extra>",
    ))
    for col, color, label in metrics:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["y_bin_centre"], y=df[col],
                name=label, line=dict(color=color, width=2),
                mode="lines",
                hovertemplate=f"Y=%{{x:.0f}} ly<br>{label}: %{{y:.4f}}<extra></extra>",
            ))
    fig.add_vline(x=0, line=dict(color="white", dash="dot", width=1),
                  annotation_text="Galactic plane")

    fig.update_layout(
        title="Valuable Body Rates vs Galactic Height (Y)",
        xaxis_title="Galactic Y (ly)",
        yaxis_title="Rate (bodies per system)",
        yaxis2=dict(title="Systems visited", overlaying="y",
                    side="right", showgrid=False),
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
        font_color="white", legend=dict(bgcolor="rgba(0,0,0,0.4)"),
    )
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


def plot_body_rate_vs_star_class_static(df: pd.DataFrame,
                                        out_path: Path | None = None) -> str | None:
    """
    Grouped bar chart: terra / ELW / WW rates per star class.
    df must have columns: star_class, systems, terra_rate, elw_rate, ww_rate, bio_rate.
    Sorted by terraformable rate descending; only classes with >= 10 systems.
    """
    if df.empty:
        return None

    df = df.sort_values("terra_rate", ascending=False).head(30)

    x = np.arange(len(df))
    width = 0.22
    fig, ax = plt.subplots(figsize=(max(10, len(df) * 0.55), 6))

    bars = [
        (df["terra_rate"], "#ffaa33", "Terraformable"),
        (df["bio_rate"],   "#44dd88", "Bio signals"),
        (df["ww_rate"],    "#4488ff", "Water Worlds"),
        (df["elw_rate"],   "#ff4455", "Earth-likes"),
    ]
    for i, (vals, color, label) in enumerate(bars):
        ax.bar(x + i * width, vals, width, color=color, label=label,
               alpha=0.85, edgecolor="none")

    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(df["star_class"], rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Rate (bodies per visited system)")
    ax.set_title("Valuable Body Rates by Primary Star Class")
    ax.legend(framealpha=0.25, labelcolor="white")
    ax.grid(axis="y")

    fig.tight_layout()
    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_body_rate_vs_star_class_interactive(df: pd.DataFrame,
                                             out_path: Path | None = None) -> go.Figure | None:
    """Interactive grouped bar chart of rates by star class."""
    if df.empty:
        return None

    df = df.sort_values("terra_rate", ascending=False).head(30)

    metrics = [
        ("terra_rate", "#ffaa33", "Terraformable"),
        ("bio_rate",   "#44dd88", "Bio signals"),
        ("ww_rate",    "#4488ff", "Water Worlds"),
        ("elw_rate",   "#ff4455", "Earth-likes"),
    ]
    fig = go.Figure()
    for col, color, label in metrics:
        if col in df.columns:
            fig.add_trace(go.Bar(
                x=df["star_class"], y=df[col], name=label,
                marker_color=color,
                hovertemplate=f"%{{x}}<br>{label}: %{{y:.4f}}<extra></extra>",
            ))

    fig.update_layout(
        barmode="group",
        title="Valuable Body Rates by Star Class",
        xaxis_title="Star class",
        yaxis_title="Rate (bodies per visited system)",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
        font_color="white", legend=dict(bgcolor="rgba(0,0,0,0.4)"),
    )
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)


def plot_tectonicas_he_distribution(df: pd.DataFrame,
                                    out_path: Path | None = None) -> go.Figure | None:
    """
    He% distribution of all boxels vs. Tectonicas-containing boxels.
    Mirrors the community 'Boxel Helium vs Tectonicas' chart.

    df must have columns: he_mean, has_tectonicas (bool).
    Returns None when there is no He% data yet.
    """
    if df.empty:
        return None

    bin_width = 0.2
    lo = max(23.0, np.floor(df["he_mean"].min() * 5) / 5)
    hi = min(34.0, np.ceil(df["he_mean"].max() * 5) / 5) + bin_width
    bins = np.arange(lo, hi, bin_width)
    if len(bins) < 2:
        return None
    centres = bins[:-1] + bin_width / 2

    all_counts, _ = np.histogram(df["he_mean"], bins=bins)
    tec_counts, _ = np.histogram(df.loc[df["has_tectonicas"], "he_mean"], bins=bins)

    total_all = all_counts.sum() or 1
    total_tec = tec_counts.sum() or 1
    all_norm = all_counts / total_all
    tec_norm = tec_counts / total_tec

    x_labels = [f"{c:.1f}" for c in centres]

    fig = go.Figure()

    # Yellow filled area: normalised Tectonicas distribution
    fig.add_trace(go.Scatter(
        x=x_labels, y=tec_norm,
        fill="tozeroy", mode="none",
        fillcolor="rgba(255,200,50,0.25)",
        name="Normalised Tectonicas",
        hovertemplate="He%: %{x}<br>Tectonicas (norm): %{y:.2%}<extra></extra>",
    ))
    # Blue line: all boxels normalised distribution
    fig.add_trace(go.Scatter(
        x=x_labels, y=all_norm,
        mode="lines", line=dict(color="#4488ff", width=2),
        name="All Boxels He%",
        hovertemplate="He%: %{x}<br>All boxels: %{y:.2%}<extra></extra>",
    ))
    # Orange line: Tectonicas boxels normalised distribution
    fig.add_trace(go.Scatter(
        x=x_labels, y=tec_norm,
        mode="lines", line=dict(color="#ff7722", width=2),
        name="Tectonicas Boxels He%",
        hovertemplate="He%: %{x}<br>Tectonicas: %{y:.2%}<extra></extra>",
    ))

    n_tec = int(df["has_tectonicas"].sum())
    n_all = len(df)
    fig.update_layout(
        title=f"Boxel He% vs Stratum Tectonicas  ({n_tec} Tectonicas boxels / {n_all} total)",
        xaxis_title="Boxel Mean He%",
        yaxis_title="Normalised Frequency",
        yaxis_tickformat=".1%",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
        font_color="white",
        legend=dict(bgcolor="rgba(0,0,0,0.4)"),
        hovermode="x unified",
    )
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# He ranges from the Tectonicas community chart (orange > 5%)
_TECTONICAS_RANGES = [(24.2, 24.5), (25.9, 26.5)]


def plot_boxel_he_vs_value(df: pd.DataFrame,
                           out_path: Path | None = None) -> go.Figure | None:
    """
    Line chart: binned He% (x) vs mean system exploration value across boxels (y).
    Bins are 0.2% wide. Includes a 2 MCr reference line and Tectonicas He% bands.
    """
    if df.empty:
        return None

    bin_width = 0.2
    lo = np.floor(df["he_mean"].min() * 5) / 5
    hi = np.ceil(df["he_mean"].max() * 5) / 5 + bin_width
    bins = np.arange(lo, hi, bin_width)
    if len(bins) < 2:
        return None

    labels = bins[:-1] + bin_width / 2
    df = df.copy()
    df["he_bin"] = pd.cut(df["he_mean"], bins=bins, labels=labels)
    binned = (
        df.groupby("he_bin", observed=True)
        .agg(avg_value=("avg_system_value", "mean"), boxel_count=("boxel", "count"))
        .reset_index()
    )
    binned["he_bin"] = binned["he_bin"].astype(float)

    threshold = 3_500_000
    fig = go.Figure()

    # Tectonicas sweet-spot bands
    for lo_r, hi_r in _TECTONICAS_RANGES:
        fig.add_vrect(
            x0=lo_r, x1=hi_r,
            fillcolor="rgba(68,204,136,0.08)",
            line_width=0,
            annotation_text="Tec zone", annotation_position="top left",
            annotation_font=dict(color="#44cc88", size=10),
        )

    # 2 MCr reference line
    fig.add_hline(
        y=threshold,
        line_dash="dash", line_color="#ffcc44", line_width=1,
        annotation_text="3.5 MCr", annotation_position="top right",
        annotation_font=dict(color="#ffcc44", size=11),
    )

    fig.add_trace(go.Scatter(
        x=binned["he_bin"],
        y=binned["avg_value"],
        mode="lines",
        line=dict(color="#4488ff", width=2),
        customdata=binned["boxel_count"].values,
        hovertemplate=(
            "He%: %{x:.1f}%<br>"
            "Avg system value: %{y:,.0f} Cr<br>"
            "Boxels in bin: %{customdata}<extra></extra>"
        ),
    ))

    fig.update_layout(
        title="Boxel He% vs Average System Value",
        xaxis_title="Boxel Mean He%",
        yaxis_title="Average System Value (Cr)",
        yaxis_tickformat=",",
        paper_bgcolor="#0a0a1a", plot_bgcolor="#0f0f2a",
        font_color="white",
        showlegend=False,
    )
    if out_path is None:
        return fig
    _write_interactive(fig, out_path)


# ---------------------------------------------------------------------------
# Spectral class distribution (catalogue panels)
# ---------------------------------------------------------------------------

_SPECTRAL_ORDER = [f"{c}{n}" for c in "OBAFGKMLTY" for n in range(10)]

# Non-main-sequence expandable prefixes (each expanded 0-9 only if present in data).
# Placed in chart order: proto-stars after Y, then giants, then S/MS.
_EXTRA_EXPANDABLE: list[str] = [
    "TTS", "AeBe",                          # proto-stars
    "O_BlueWhiteSuperGiant",                # O supergiant
    "B_BlueWhiteSuperGiant",                # B supergiant
    "A_BlueWhiteSuperGiant",                # A supergiant
    "F_WhiteSuperGiant",                    # F supergiant
    "G_WhiteSuperGiant",                    # G supergiant
    "K_OrangeGiant", "K_OrangeSuperGiant",  # K giant/supergiant
    "M_RedGiant",    "M_RedSuperGiant",     # M giant/supergiant
    "MS", "S",                              # S-type/MS-type
]

# Short display labels for chart tick marks (prefix → abbreviated form)
_BASE_SHORT: dict[str, str] = {
    "TTS": "TTS", "AeBe": "AeBe",
    "O_BlueWhiteSuperGiant": "O_BSG",
    "B_BlueWhiteSuperGiant": "B_BSG",
    "A_BlueWhiteSuperGiant": "A_BSG",
    "F_WhiteSuperGiant":     "F_WSG",
    "G_WhiteSuperGiant":     "G_WSG",
    "K_OrangeGiant":         "K_OG",
    "K_OrangeSuperGiant":    "K_OSG",
    "M_RedGiant":            "M_RG",
    "M_RedSuperGiant":       "M_RSG",
    "MS": "MS", "S": "S",
}

# Remaining special types collapsed to single aggregated points.
_COMPACT_GROUP_DEFS: list[tuple[str, list[str]]] = [
    ("C★", [
        "C", "CH", "CHd", "CJ", "CN", "CS",
        *[f"C{n}"   for n in range(10)],
        *[f"CJ{n}"  for n in range(10)],
        *[f"CN{n}"  for n in range(10)],
        *[f"CS{n}"  for n in range(10)],
        *[f"CH{n}"  for n in range(10)],
        *[f"CHd{n}" for n in range(10)],
    ]),
    ("W-R", [
        "W", "WN", "WNC", "WC", "WO",
        *[f"WN{n}"  for n in range(10)],
        *[f"WNC{n}" for n in range(10)],
        *[f"WC{n}"  for n in range(10)],
        *[f"WO{n}"  for n in range(10)],
        *[f"W{n}"   for n in range(10)],
    ]),
    ("WD", [
        "D", "DA", "DAB", "DAO", "DAZ", "DAV",
        "DB", "DBZ", "DBV", "DO", "DOV", "DQ", "DC", "DCV", "DX",
        *[f"D{n}"   for n in range(10)],
        *[f"DA{n}"  for n in range(10)],
        *[f"DB{n}"  for n in range(10)],
        *[f"DC{n}"  for n in range(10)],
        *[f"DO{n}"  for n in range(10)],
    ]),
    ("NS", ["N", *[f"N{n}" for n in range(10)]]),
    ("BH", ["H", *[f"H{n}" for n in range(10)]]),
]

_COMPACT_GROUP_ORDER  = [g for g, _ in _COMPACT_GROUP_DEFS]
_COMPACT_KEY_TO_GROUP: dict[str, str] = {
    k: group for group, keys in _COMPACT_GROUP_DEFS for k in keys
}


def plot_spectral_distribution(counts: pd.Series,
                                title: str = "",
                                totals: pd.Series | None = None) -> str | None:
    """
    Line chart of scan/body count by detailed spectral subclass (G2, F5, …).
    counts: Series indexed by spectral_class strings, values are integer counts.
    totals: optional Series of total planet counts per spectral class (same index);
            when provided a second right y-axis shows the occurrence percentage.
    Returns a base64 PNG string, or None if no data.

    Main-sequence (OBAFGKMLTY) and expandable non-MS classes (TTS, AeBe, giants,
    S, MS) are each shown as a full 0-9 series — only if at least one subclass
    entry is present in the data, so the chart never grows needlessly wide.
    Remaining types (C★, W-R, WD, NS, BH) collapse to single aggregated points.
    Labels appear at *0 and *5 for expanded classes; always for compact points.
    """
    if counts.empty:
        return None

    # Drop any non-string index entries (e.g. NaN / float from NULL rows)
    counts = counts[counts.index.map(lambda k: isinstance(k, str))]
    if counts.empty:
        return None

    index_set = set(counts.index)

    # ── Collect expandable bases (only when at least one subclass present) ────
    expandable_bases: list[str] = []
    seen: set[str] = set()

    # Main sequence (single-char, from hot→cool order)
    for k in _SPECTRAL_ORDER:
        base = k[0]
        if base not in seen and k in index_set:
            seen.add(base)
            expandable_bases.append(base)

    # Extra expandable (multi-char or non-OBAFGKMLTY single-char)
    for base in _EXTRA_EXPANDABLE:
        if base not in seen and any(f"{base}{n}" in index_set for n in range(10)):
            seen.add(base)
            expandable_bases.append(base)

    # Build key→base lookup and full expanded key list
    key_to_base: dict[str, str] = {}
    expanded_keys: list[str] = []
    for base in expandable_bases:
        for n in range(10):
            k = f"{base}{n}"
            expanded_keys.append(k)
            key_to_base[k] = base
    expanded_set = set(expanded_keys)

    # ── Aggregate remaining keys into compact display points ──────────────────
    group_totals: dict[str, float] = {}
    unmatched: list[str] = []
    for k in index_set:
        if k in expanded_set:
            continue
        # Bare extra-expandable prefix without digit (very rare) → fold into *0
        for base in _EXTRA_EXPANDABLE:
            if k == base and base in seen:
                group_totals[f"{base}0"] = group_totals.get(f"{base}0", 0.0) + float(counts[k])
                break
        else:
            group = _COMPACT_KEY_TO_GROUP.get(k)
            if group:
                group_totals[group] = group_totals.get(group, 0.0) + float(counts[k])
            else:
                unmatched.append(k)

    compact_keys = [g for g in _COMPACT_GROUP_ORDER if g in group_totals]
    other_keys   = sorted(set(unmatched))

    # ── Build combined value series (NaN spacers between compact points) ───────
    # Each compact group label gets 3 blank NaN-valued positions before it so
    # the rotated tick labels don't overlap.  Spacers are identified by a
    # sentinel prefix "_sp" and are excluded from separators/labels.
    _COMPACT_GAP = 3

    compact_section: list[tuple[str, float]] = []
    for i, g in enumerate(compact_keys + other_keys):
        if i > 0:
            for j in range(_COMPACT_GAP):
                compact_section.append((f"_sp{i}_{j}", float("nan")))
        val = group_totals[g] if g in group_totals else (
            float(counts[g]) if g in index_set else 0.0)
        compact_section.append((g, val))

    compact_section_keys = [k for k, _ in compact_section]
    compact_section_ys   = [v for _, v in compact_section]
    spacer_set = {k for k in compact_section_keys if k.startswith("_sp")}

    all_keys = expanded_keys + compact_section_keys
    if not all_keys:
        return None

    def _val(k: str) -> float:
        if k in group_totals:
            return group_totals[k]
        return float(counts[k]) if k in index_set else 0.0

    ys = [_val(k) for k in expanded_keys] + compact_section_ys

    # ── Labels (short form for long prefixes; *0/*5 for expanded) ─────────────
    labels: list[str] = []
    for k in all_keys:
        if k in spacer_set:
            labels.append("")
        elif k in expanded_set:
            base   = key_to_base[k]
            digit  = k[len(base):]          # single digit character
            short  = _BASE_SHORT.get(base, base)
            labels.append(f"{short}{digit}" if digit in ("0", "5") else "")
        else:
            labels.append(k)

    xs = list(range(len(all_keys)))

    # ── Compute percentage series if totals provided ───────────────────────────
    pct_ys: list[float] | None = None
    if totals is not None and not totals.empty:
        def _pct(k: str, y: float) -> float:
            if k in spacer_set or np.isnan(y):
                return float("nan")
            if k in expanded_set:
                denom = float(totals.get(k, 0) or 0)
            else:
                # Compact group key: sum totals for all member spectral classes
                denom = sum(
                    float(totals.get(orig_k, 0) or 0)
                    for orig_k, grp in _COMPACT_KEY_TO_GROUP.items()
                    if grp == k
                )
            return (y / denom * 100.0) if denom > 0 else float("nan")

        pct_ys = [_pct(k, y) for k, y in zip(all_keys, ys)]

    fig, ax = plt.subplots(figsize=(9, 1.8))
    display_title = f"Spectral Distribution – {title}" if title else "Spectral Distribution"
    ax.set_title(display_title, fontsize=6.5, color="#9999cc", pad=3)
    ax.plot(xs, ys, color="#4488cc", linewidth=1.5, zorder=3)
    ax.fill_between(xs, ys, alpha=0.18, color="#4488cc", zorder=2)

    if pct_ys is not None:
        ax2 = ax.twinx()
        ax2.plot(xs, pct_ys, color="#cc8833", linewidth=1.2,
                 linestyle="--", zorder=4, alpha=0.85)
        ax2.set_ylabel("%", fontsize=7, color="#cc8833")
        ax2.tick_params(axis="y", labelsize=6, colors="#cc8833")
        ax2.set_ylim(bottom=0)
        ax2.yaxis.set_major_locator(mticker.MaxNLocator(integer=False, nbins=3))
        ax2.spines["right"].set_color("#cc8833")
        ax2.yaxis.grid(True, color="#cc8833", linewidth=0.4,
                       alpha=0.15, linestyle="-", zorder=0)

    # Dashed separators between expanded classes; solid line before compact section
    prev_base: str | None = None
    compact_separator_drawn = False
    for i, key in enumerate(all_keys):
        if key in spacer_set:
            continue
        if key in expanded_set:
            base = key_to_base[key]
            if prev_base is not None and base != prev_base:
                ax.axvline(i - 0.5, color="#334466", linewidth=0.6, linestyle="--", zorder=1)
            prev_base = base
        elif not compact_separator_drawn and i > 0:
            ax.axvline(i - 0.5, color="#556688", linewidth=0.9, linestyle="-", zorder=1)
            compact_separator_drawn = True

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=90, fontsize=5.5)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(-0.5, len(xs) - 0.5)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=4))
    ax.set_ylabel("Count", fontsize=7)
    ax.yaxis.grid(True, color="white", linewidth=0.4, alpha=0.12, linestyle="-", zorder=0)
    ax.set_axisbelow(True)

    return _fig_to_b64(fig)

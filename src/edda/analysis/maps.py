"""
Galaxy map generation — static (matplotlib) and interactive (plotly).

The Milky Way coordinate system in Elite Dangerous:
  X: galactic longitude (positive = towards Orion arm / antispinward)
  Y: vertical above/below galactic plane
  Z: galactic latitude (positive = towards Sagittarius A*)
Sol is at (0, 0, 0).

When out_path is None, static functions return a base64 PNG string and
interactive functions return a go.Figure — used by the dashboard builder.
"""

import base64
import io
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from .stats import SECTOR_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _save_static(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved: {path}")


def _write_interactive(fig: go.Figure, out_path: Path) -> None:
    fig.write_html(str(out_path))
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# Reference landmarks (ED galactic coordinates)
# ---------------------------------------------------------------------------

# (name, x, y, z, colour)
_LANDMARKS = [
    ("Sol",           0,           0,           0,           "yellow"),
    ("Colonia",      -9530.5,     -910.28125,  19808.125,   "#ff9944"),
    ("Sag A*",        25.21875,   -20.90625,   25899.96875, "#ff44aa"),
    ("Beagle Point", -1111.5625,  -134.21875,  65269.75,    "#44ffcc"),
]


def _mark_landmarks_2d(ax, use_y: bool = False) -> None:
    """Scatter + annotate all landmarks on a 2D matplotlib axis.

    use_y=False → top-down view (X vs Z).
    use_y=True  → side view (X vs Y).
    """
    for name, lx, ly, lz, colour in _LANDMARKS:
        coord2 = ly if use_y else lz
        sym = "*" if name == "Sol" else "D"
        ax.scatter([lx], [coord2], color=colour, s=60, zorder=6, marker=sym)
        ax.annotate(name, (lx, coord2), color=colour, fontsize=8,
                    xytext=(4, 4), textcoords="offset points")


def _mark_landmarks_3d(ax) -> None:
    """Scatter + text all landmarks on a matplotlib 3D axis."""
    for name, lx, ly, lz, colour in _LANDMARKS:
        ax.scatter([lx], [ly], [lz], color=colour, s=80, zorder=6)
        ax.text(lx, ly, lz, f"  {name}", color=colour, fontsize=8)


def _landmark_trace_2d() -> go.Scatter:
    """Single Plotly Scatter trace with all landmarks for 2D maps (X vs Z)."""
    return go.Scatter(
        x=[r[1] for r in _LANDMARKS],
        y=[r[3] for r in _LANDMARKS],
        mode="markers+text",
        marker=dict(color=[r[4] for r in _LANDMARKS], size=10, symbol="star"),
        text=[r[0] for r in _LANDMARKS],
        textposition="top right",
        textfont=dict(color="white", size=11),
        name="Landmarks",
        showlegend=True,
        hovertemplate=(
            "<b>%{text}</b><br>(%{x:.1f}, %{y:.1f}) ly<extra></extra>"
        ),
    )


def _landmark_trace_3d() -> go.Scatter3d:
    """Single Plotly Scatter3d trace with all landmarks for 3D maps."""
    return go.Scatter3d(
        x=[r[1] for r in _LANDMARKS],
        y=[r[2] for r in _LANDMARKS],
        z=[r[3] for r in _LANDMARKS],
        mode="markers+text",
        marker=dict(color=[r[4] for r in _LANDMARKS], size=8, symbol="diamond"),
        text=[r[0] for r in _LANDMARKS],
        textposition="top right",
        textfont=dict(color="white", size=11),
        name="Landmarks",
        hovertemplate=(
            "<b>%{text}</b><br>(%{x:.1f}, %{y:.1f}, %{z:.1f}) ly<extra></extra>"
        ),
    )


# ---------------------------------------------------------------------------
# Current player position helpers
# ---------------------------------------------------------------------------

def _mark_current_pos_2d(ax, pos: dict, use_y: bool = False) -> None:
    coord2 = pos["y"] if use_y else pos["z"]
    ax.scatter([pos["x"]], [coord2], color="white", s=150, zorder=7,
               marker="X", linewidths=1.5, edgecolors="#ffcc00")
    ax.annotate("CMDR", (pos["x"], coord2), color="white", fontsize=9,
                fontweight="bold", xytext=(5, 5), textcoords="offset points")


def _mark_current_pos_3d(ax, pos: dict) -> None:
    ax.scatter([pos["x"]], [pos["y"]], [pos["z"]], color="white", s=150,
               zorder=7, marker="X")
    ax.text(pos["x"], pos["y"], pos["z"], "  CMDR", color="white",
            fontsize=9, fontweight="bold")


def _current_pos_trace_2d(pos: dict) -> go.Scatter:
    return go.Scatter(
        x=[pos["x"]], y=[pos["z"]],
        mode="markers+text",
        marker=dict(color="white", size=14, symbol="x",
                    line=dict(color="#ffcc00", width=2)),
        text=["CMDR"],
        textposition="top right",
        textfont=dict(color="white", size=12),
        name="Current Location",
        showlegend=True,
        customdata=[pos["name"]],
        hovertemplate=(
            "<b>CMDR — %{customdata}</b><br>(%{x:.1f}, %{y:.1f}) ly<extra></extra>"
        ),
    )


def _current_pos_trace_3d(pos: dict) -> go.Scatter3d:
    return go.Scatter3d(
        x=[pos["x"]], y=[pos["y"]], z=[pos["z"]],
        mode="markers+text",
        marker=dict(color="white", size=10, symbol="cross",
                    line=dict(color="#ffcc00", width=2)),
        text=["CMDR"],
        textposition="top right",
        textfont=dict(color="white", size=12),
        name="Current Location",
        customdata=[[pos["name"]]],
        hovertemplate=(
            "<b>CMDR — %{customdata[0]}</b><br>"
            "(%{x:.1f}, %{y:.1f}, %{z:.1f}) ly<extra></extra>"
        ),
    )


# ---------------------------------------------------------------------------
# Static matplotlib maps
# ---------------------------------------------------------------------------

def plot_galaxy_map_static(df: pd.DataFrame, out_path: Path | None,
                           colour_by: str = "density",
                           current_pos: dict | None = None) -> str | None:
    """
    Top-down galactic map (X vs Z plane).

    colour_by: 'density' | 'bio' | 'first_discovery'
    Returns base64 PNG string when out_path is None.
    """
    fig, ax = plt.subplots(figsize=(16, 12), facecolor="#0a0a1a")
    ax.set_facecolor("#0a0a1a")

    if df.empty:
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                color="white", ha="center")
        if out_path is None:
            return _fig_to_b64(fig)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return None

    if colour_by == "bio":
        c = df["total_bio_signals"].clip(upper=10)
        cmap = "YlGn"
        label = "Bio signals"
    elif colour_by == "first_discovery":
        c = df["any_first_discovery"].astype(float)
        cmap = "cool"
        label = "First discovery"
    else:
        c = "steelblue"
        cmap = None
        label = None

    if colour_by == "density":
        hb = ax.hexbin(df["x"], df["z"], gridsize=200,
                       cmap="inferno", mincnt=1, linewidths=0)
        cb = fig.colorbar(hb, ax=ax, label="Systems per cell")
        cb.ax.yaxis.label.set_color("white")
        cb.ax.tick_params(colors="white")
    else:
        sc = ax.scatter(df["x"], df["z"], c=c, cmap=cmap,
                        s=1.5, alpha=0.6, linewidths=0)
        cb = fig.colorbar(sc, ax=ax, label=label)
        cb.ax.yaxis.label.set_color("white")
        cb.ax.tick_params(colors="white")

    _mark_landmarks_2d(ax)
    if current_pos:
        _mark_current_pos_2d(ax, current_pos)

    ax.set_xlabel("X (ly)", color="white")
    ax.set_ylabel("Z (ly)", color="white")
    ax.set_title("EDDA — Visited Systems", color="white", fontsize=14)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")

    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_galaxy_side_view_static(df: pd.DataFrame, out_path: Path | None,
                                 current_pos: dict | None = None) -> str | None:
    """Side view (X vs Y) to show galactic-plane thickness of route."""
    fig, ax = plt.subplots(figsize=(16, 6), facecolor="#0a0a1a")
    ax.set_facecolor("#0a0a1a")

    if not df.empty:
        ax.scatter(df["x"], df["y"], s=1, alpha=0.4, color="steelblue", linewidths=0)
    _mark_landmarks_2d(ax, use_y=True)
    if current_pos:
        _mark_current_pos_2d(ax, current_pos, use_y=True)

    ax.set_xlabel("X (ly)", color="white")
    ax.set_ylabel("Y (ly)", color="white")
    ax.set_title("EDDA — Side View (galactic plane)", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")

    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Interactive Plotly maps
# ---------------------------------------------------------------------------

def plot_galaxy_map_interactive(df: pd.DataFrame, out_path: Path | None,
                                colour_by: str = "bodies_scanned",
                                current_pos: dict | None = None) -> go.Figure | None:
    """
    Interactive top-down galaxy map saved as self-contained HTML.

    colour_by: any numeric column in df — 'bodies_scanned', 'total_bio_signals', etc.
    Returns go.Figure when out_path is None.
    """
    if df.empty:
        if out_path:
            out_path.write_text("<p>No data</p>")
        return None

    hover_cols = ["name", "star_class", "bodies_scanned",
                  "total_bio_signals", "any_first_discovery"]
    hover_cols = [c for c in hover_cols if c in df.columns]

    fig = px.scatter(
        df, x="x", y="z",
        color=colour_by,
        color_continuous_scale="Viridis",
        hover_data=hover_cols,
        title="Elite Dangerous — Visited Systems (interactive)",
        labels={"x": "X (ly)", "z": "Z (ly)", colour_by: colour_by},
        opacity=0.7,
    )
    fig.update_traces(marker=dict(size=3))
    fig.update_layout(
        paper_bgcolor="#0a0a1a",
        plot_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1,
        ),
    )
    fig.add_trace(_landmark_trace_2d())
    if current_pos:
        fig.add_trace(_current_pos_trace_2d(current_pos))

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Bio heatmap
# ---------------------------------------------------------------------------

def plot_bio_heatmap_interactive(df: pd.DataFrame, out_path: Path | None,
                                 current_pos: dict | None = None) -> go.Figure | None:
    """Density map coloured by bio signal count."""
    bio_df = df[df["total_bio_signals"] > 0].copy()
    return plot_galaxy_map_interactive(bio_df, out_path,
                                       colour_by="total_bio_signals",
                                       current_pos=current_pos)


# ---------------------------------------------------------------------------
# Sector maps — 3D with cube geometry
# ---------------------------------------------------------------------------

_HALF = SECTOR_SIZE / 2

# 8 vertex offsets for a unit cube scaled to _HALF
_VERT_OFFSETS = np.array([
    [-1, -1, -1], [+1, -1, -1], [+1, +1, -1], [-1, +1, -1],
    [-1, -1, +1], [+1, -1, +1], [+1, +1, +1], [-1, +1, +1],
], dtype=float) * _HALF

# 12 triangular faces (6 sides × 2 triangles each)
_FACE_TRIS = np.array([
    [0, 1, 2], [0, 2, 3],   # -Z face
    [4, 5, 6], [4, 6, 7],   # +Z face
    [0, 1, 5], [0, 5, 4],   # -Y face
    [3, 2, 6], [3, 6, 7],   # +Y face
    [0, 3, 7], [0, 7, 4],   # -X face
    [1, 2, 6], [1, 6, 5],   # +X face
])


def _build_cube_mesh(df: pd.DataFrame):
    """
    Vectorised construction of a single concatenated cube mesh for all sectors.

    Returns (x, y, z, i, j, k, intensity) where intensity is log10(system_count)
    repeated for every vertex so Mesh3d can colour each cube uniformly.
    """
    n = len(df)
    centroids = df[["grid_cx", "grid_cy", "grid_cz"]].to_numpy()

    # (n, 8, 3) — broadcast vertex offsets onto each centroid
    verts = centroids[:, np.newaxis, :] + _VERT_OFFSETS[np.newaxis, :, :]
    verts_flat = verts.reshape(-1, 3)   # (n*8, 3)

    # (n, 12, 3) — offset local face indices by the base vertex of each cube
    base = (np.arange(n) * 8)[:, np.newaxis, np.newaxis]
    faces = _FACE_TRIS[np.newaxis, :, :] + base   # broadcast
    faces_flat = faces.reshape(-1, 3)              # (n*12, 3)

    # log-scale intensity, same value for all 8 vertices of each cube
    log_counts = np.log10(df["system_count"].to_numpy().clip(min=1))
    intensity = np.repeat(log_counts, 8)

    return (
        verts_flat[:, 0], verts_flat[:, 1], verts_flat[:, 2],
        faces_flat[:, 0], faces_flat[:, 1], faces_flat[:, 2],
        intensity,
    )


def plot_sector_map_static(df: pd.DataFrame, out_path: Path | None,
                           top_n: int = 200,
                           current_pos: dict | None = None) -> str | None:
    """
    3D sector map rendered with matplotlib bar3d.

    Draws actual 1200 ly cubes.  Limited to top_n sectors by system count
    because matplotlib's 3D renderer is CPU-bound.
    Returns base64 PNG string when out_path is None.
    """
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  registers the projection

    if df.empty:
        return None

    plot_df = df.head(top_n)
    counts = plot_df["system_count"].to_numpy(dtype=float)
    norm = plt.matplotlib.colors.LogNorm(vmin=counts.min(), vmax=counts.max())
    cmap = plt.cm.plasma
    colors = cmap(norm(counts))

    fig = plt.figure(figsize=(14, 10), facecolor="#0a0a1a")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#0a0a1a")

    for (_, row), color in zip(plot_df.iterrows(), colors):
        ax.bar3d(
            row.grid_cx - _HALF,
            row.grid_cy - _HALF,
            row.grid_cz - _HALF,
            SECTOR_SIZE, SECTOR_SIZE, SECTOR_SIZE,
            color=color, alpha=0.75, shade=True,
        )

    _mark_landmarks_3d(ax)
    if current_pos:
        _mark_current_pos_3d(ax, current_pos)

    ax.set_xlabel("X (ly)", color="white", labelpad=8)
    ax.set_ylabel("Y (ly)", color="white", labelpad=8)
    ax.set_zlabel("Z (ly)", color="white", labelpad=8)
    ax.tick_params(colors="white")
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor("#333355")
    ax.yaxis.pane.set_edgecolor("#333355")
    ax.zaxis.pane.set_edgecolor("#333355")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=ax, shrink=0.5, pad=0.1, label="Systems visited")
    cb.ax.yaxis.label.set_color("white")
    cb.ax.tick_params(colors="white")

    ax.set_title(
        f"EDDA — Sector Heat Map 3D  (top {top_n} of {len(df):,} sectors)",
        color="white", fontsize=12, pad=12,
    )

    if out_path is None:
        return _fig_to_b64(fig)
    _save_static(fig, out_path)
    return None


def plot_sector_map_interactive(df: pd.DataFrame, out_path: Path | None,
                                current_pos: dict | None = None) -> go.Figure | None:
    """
    Interactive 3D sector map.

    All sectors are rendered as 1200 ly cubes in a single Mesh3d trace
    (fully vectorised — no Python loop per sector).  Hover data is stored
    as per-vertex customdata so mousing over any face of a cube shows the
    correct sector name and stats.
    Returns go.Figure when out_path is None.
    """
    if df.empty:
        if out_path:
            out_path.write_text("<p>No data</p>")
        return None

    x, y, z, fi, fj, fk, intensity = _build_cube_mesh(df)

    # Per-vertex customdata: repeat each sector's values for all 8 vertices.
    # Columns: [sector_name, system_count, grid_cx, grid_cy, grid_cz]
    custom_per_sector = np.column_stack([
        df["sector"].to_numpy(),
        df["system_count"].to_numpy().astype(str),
        df["grid_cx"].to_numpy().astype(int).astype(str),
        df["grid_cy"].to_numpy().astype(int).astype(str),
        df["grid_cz"].to_numpy().astype(int).astype(str),
    ])
    customdata = np.repeat(custom_per_sector, 8, axis=0)  # (n*8, 5)

    cube_trace = go.Mesh3d(
        x=x, y=y, z=z,
        i=fi, j=fj, k=fk,
        intensity=intensity,
        colorscale="Plasma",
        colorbar=dict(
            title=dict(text="log₁₀(systems)", font=dict(color="white")),
            tickfont=dict(color="white"),
        ),
        opacity=0.75,
        customdata=customdata,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Systems visited: %{customdata[1]}<br>"
            "Grid centre: (%{customdata[2]}, %{customdata[3]}, %{customdata[4]}) ly"
            "<extra></extra>"
        ),
        name="Sectors",
        showscale=True,
        flatshading=True,
    )

    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []
    fig = go.Figure(data=[cube_trace, _landmark_trace_3d()] + extra)
    fig.update_layout(
        title=dict(
            text=f"Elite Dangerous — Sector Heat Map 3D  ({len(df):,} sectors, 1200 ly cubes)",
            font=dict(color="white"),
        ),
        scene=dict(
            xaxis=dict(title="X (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[50000, -50000]),
            yaxis=dict(title="Y (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-16000, 9000]),
            zaxis=dict(title="Z (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-24000, 76000]),
            bgcolor="#0a0a1a",
            aspectmode="manual",
            aspectratio=dict(x=1, y=0.25, z=1),
            camera=dict(
                eye=dict(x=0.0, y=1.2, z=-1.8),
                up=dict(x=0, y=1, z=0),
            ),
        ),
        paper_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None

# ---------------------------------------------------------------------------
# Species bubble map — 3D scatter, one bubble per system
# ---------------------------------------------------------------------------

def plot_species_bubble_3d(df: pd.DataFrame, species: str,
                           out_path: Path | None = None,
                           current_pos: dict | None = None) -> go.Figure | None:
    """
    3D bubble map showing every system where *species* was found.

    Bubble size scales with sqrt(scan_count) so high-density systems stand
    out without completely dwarfing single-scan systems.
    """
    if df.empty:
        if out_path:
            out_path.write_text("<p>No data</p>")
        return None

    counts = df["scan_count"].to_numpy(dtype=float)

    # sqrt scaling: smallest bubble = 6, largest = 28
    sqrt_counts = np.sqrt(counts)
    lo, hi = sqrt_counts.min(), sqrt_counts.max()
    if hi > lo:
        sizes = 6 + 22 * (sqrt_counts - lo) / (hi - lo)
    else:
        sizes = np.full(len(counts), 14.0)

    species_trace = go.Scatter3d(
        x=df["x"].tolist(),
        y=df["y"].tolist(),
        z=df["z"].tolist(),
        mode="markers",
        marker=dict(
            size=sizes.tolist(),
            color=counts.tolist(),
            colorscale="YlGn",
            colorbar=dict(
                title=dict(text="Scans", font=dict(color="white")),
                tickfont=dict(color="white"),
            ),
            opacity=0.85,
            line=dict(width=0),
        ),
        text=df["system_name"].tolist(),
        customdata=counts.astype(int).tolist(),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Scans: %{customdata}<br>"
            "(%{x:.1f}, %{y:.1f}, %{z:.1f}) ly"
            "<extra></extra>"
        ),
        name=species,
    )

    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []
    fig = go.Figure(data=[species_trace, _landmark_trace_3d()] + extra)
    fig.update_layout(
        title=dict(
            text=f"{species} — System Locations ({len(df):,} systems)",
            font=dict(color="white"),
        ),
        scene=dict(
            xaxis=dict(title="X (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[50000, -50000]),
            yaxis=dict(title="Y (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-16000, 9000]),
            zaxis=dict(title="Z (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-24000, 76000]),
            bgcolor="#0a0a1a",
            aspectmode="manual",
            aspectratio=dict(x=1, y=0.25, z=1),
            camera=dict(
                eye=dict(x=0.0, y=1.2, z=-1.8),
                up=dict(x=0, y=1, z=0),
            ),
        ),
        paper_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Valuable-regions sector map — cubes coloured by rate metric
# ---------------------------------------------------------------------------

_RATE_META = {
    "terra_rate":   ("Terraformable rate",   "YlOrRd"),
    "elw_rate":     ("Earth-like rate",      "Reds"),
    "ww_rate":      ("Water World rate",     "Blues"),
    "ammonia_rate": ("Ammonia World rate",   "Greens"),
    "bio_rate":     ("Bio-signal rate",      "YlGn"),
}


def plot_sector_valuable_map_interactive(
    df: pd.DataFrame,
    out_path: Path | None = None,
    metric: str = "terra_rate",
    current_pos: dict | None = None,
) -> go.Figure | None:
    """
    Interactive 3D sector map coloured by a rate metric (bodies per system).

    df must come from stats.sector_valuable_data() which adds elw_rate,
    ww_rate, terra_rate, bio_rate columns.
    metric — one of 'terra_rate', 'elw_rate', 'ww_rate', 'bio_rate'.
    Only sectors with system_count >= 3 are shown to suppress noise.
    """
    if df.empty or metric not in df.columns:
        if out_path:
            out_path.write_text("<p>No data</p>")
        return None

    plot_df = df[(df["system_count"] >= 3) & (df[metric] > 0)].copy()
    if plot_df.empty:
        if out_path:
            out_path.write_text("<p>Insufficient data</p>")
        return None

    label, colorscale = _RATE_META.get(metric, ("Rate", "Plasma"))

    x, y, z, fi, fj, fk, _ = _build_cube_mesh(plot_df)
    intensity = np.repeat(plot_df[metric].to_numpy(), 8)

    count_col  = metric.replace("_rate", "_count")
    count_vals = plot_df[count_col].to_numpy() if count_col in plot_df.columns else np.zeros(len(plot_df))

    custom_per_sector = np.column_stack([
        plot_df["sector"].to_numpy(),
        plot_df["system_count"].to_numpy().astype(str),
        plot_df[metric].to_numpy().round(4).astype(str),
        count_vals.astype(int).astype(str),
    ])
    customdata = np.repeat(custom_per_sector, 8, axis=0)

    cube_trace = go.Mesh3d(
        x=x, y=y, z=z,
        i=fi, j=fj, k=fk,
        intensity=intensity,
        colorscale=colorscale,
        colorbar=dict(
            title=dict(text=label, font=dict(color="white")),
            tickfont=dict(color="white"),
        ),
        opacity=0.80,
        customdata=customdata,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            f"{label}: %{{customdata[2]}}<br>"
            "Bodies: %{customdata[3]}<br>"
            "Systems visited: %{customdata[1]}"
            "<extra></extra>"
        ),
        name="Sectors",
        showscale=True,
        flatshading=True,
    )

    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []
    fig = go.Figure(data=[cube_trace, _landmark_trace_3d()] + extra)
    fig.update_layout(
        title=dict(
            text=f"Sector {label}  ({len(plot_df):,} sectors, 1200 ly cubes)",
            font=dict(color="white"),
        ),
        scene=dict(
            xaxis=dict(title="X (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[50000, -50000]),
            yaxis=dict(title="Y (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-16000, 9000]),
            zaxis=dict(title="Z (ly)", color="white", gridcolor="#333355",
                       showbackground=False, range=[-24000, 76000]),
            bgcolor="#0a0a1a",
            aspectmode="manual",
            aspectratio=dict(x=1, y=0.25, z=1),
            camera=dict(
                eye=dict(x=0.0, y=1.2, z=-1.8),
                up=dict(x=0, y=1, z=0),
            ),
        ),
        paper_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None

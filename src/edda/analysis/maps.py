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
import colorsys
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
# Galactic region overlay helpers
# ---------------------------------------------------------------------------
# Region bitmap parameters from klightspeed/EliteDangerousRegionMap
_REG_X0    = -49985.0       # game X at pixel column 0
_REG_Z0    = -24105.0       # game Z at bitmap row 0  (row 0 = minimum Z)
_REG_PX_SZ =  4096.0 / 83  # ly per pixel (≈ 49.35 ly)

_region_bm_cache: dict[int, np.ndarray] = {}


def _get_region_bm(stride: int = 4) -> np.ndarray:
    """Decode RLE regionmap to a subsampled uint8 array. Cached per stride."""
    if stride in _region_bm_cache:
        return _region_bm_cache[stride]
    from edda.analysis._region_map_data import regionmap as _rle
    bm = np.zeros((2048, 2048), dtype=np.uint8)
    for zi, row in enumerate(_rle):
        xi = 0
        for length, rid in row:
            bm[zi, xi:xi + length] = rid
            xi += length
    if stride > 1:
        bm = bm[::stride, ::stride]
    _region_bm_cache[stride] = bm
    return bm


def _region_boundary_segments(stride: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Vectorised boundary extraction. Returns (xs, zs) with NaN separators —
    one segment per cell-boundary edge, placed at the exact midpoint between cells.
    Each boundary edge is represented exactly once (no double lines).
    """
    bm    = _get_region_bm(stride)
    sc    = _REG_PX_SZ * stride
    named = bm > 0

    # Horizontal edges: boundary between row z and row z+1
    h_mask          = (bm[:-1, :] != bm[1:, :]) & (named[:-1, :] | named[1:, :])
    hz, hx          = np.where(h_mask)
    h_x0            = hx         * sc + _REG_X0
    h_x1            = (hx + 1)   * sc + _REG_X0
    h_z             = (hz + 0.5) * sc + _REG_Z0   # midpoint between the two rows
    h_nan           = np.full(len(hz), np.nan)
    h_xs            = np.column_stack([h_x0, h_x1, h_nan]).ravel()
    h_zs            = np.column_stack([h_z,  h_z,  h_nan]).ravel()

    # Vertical edges: boundary between col x and col x+1
    v_mask          = (bm[:, :-1] != bm[:, 1:]) & (named[:, :-1] | named[:, 1:])
    vz, vx          = np.where(v_mask)
    v_x             = (vx + 0.5) * sc + _REG_X0   # midpoint between the two cols
    v_z0            = vz          * sc + _REG_Z0
    v_z1            = (vz + 1)    * sc + _REG_Z0
    v_nan           = np.full(len(vz), np.nan)
    v_xs            = np.column_stack([v_x, v_x,  v_nan]).ravel()
    v_zs            = np.column_stack([v_z0, v_z1, v_nan]).ravel()

    return np.concatenate([h_xs, v_xs]), np.concatenate([h_zs, v_zs])


def _region_boundary_polylines(stride: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Same boundary edges as _region_boundary_segments but adjacent collinear
    stubs are merged into continuous polylines before NaN separators are
    inserted.  This produces solid lines in Plotly 3D instead of dashes.
    """
    bm    = _get_region_bm(stride)
    sc    = _REG_PX_SZ * stride
    named = bm > 0

    all_xs: list[np.ndarray] = []
    all_zs: list[np.ndarray] = []

    # ── Horizontal runs (same bitmap row, consecutive x) ─────────────────
    h_mask = (bm[:-1, :] != bm[1:, :]) & (named[:-1, :] | named[1:, :])
    hz, hx = np.where(h_mask)
    if len(hz):
        order = np.lexsort([hx, hz])           # sort by (row, col)
        hz, hx = hz[order], hx[order]
        # break whenever row changes or x is not the next column
        brk = np.where((hz[1:] != hz[:-1]) | (hx[1:] != hx[:-1] + 1))[0] + 1
        s, e = np.concatenate([[0], brk]), np.concatenate([brk - 1, [len(hz) - 1]])
        x0  = hx[s]         * sc + _REG_X0
        x1  = (hx[e] + 1)   * sc + _REG_X0
        z   = (hz[s] + 0.5) * sc + _REG_Z0
        nan = np.full(len(s), np.nan)
        all_xs.append(np.column_stack([x0, x1, nan]).ravel())
        all_zs.append(np.column_stack([z,  z,  nan]).ravel())

    # ── Vertical runs (same bitmap column, consecutive z) ─────────────────
    v_mask = (bm[:, :-1] != bm[:, 1:]) & (named[:, :-1] | named[:, 1:])
    vz, vx = np.where(v_mask)
    if len(vz):
        order = np.lexsort([vz, vx])           # sort by (col, row)
        vz, vx = vz[order], vx[order]
        brk = np.where((vx[1:] != vx[:-1]) | (vz[1:] != vz[:-1] + 1))[0] + 1
        s, e = np.concatenate([[0], brk]), np.concatenate([brk - 1, [len(vz) - 1]])
        x   = (vx[s] + 0.5) * sc + _REG_X0
        z0  = vz[s]          * sc + _REG_Z0
        z1  = (vz[e] + 1)    * sc + _REG_Z0
        nan = np.full(len(s), np.nan)
        all_xs.append(np.column_stack([x,  x,  nan]).ravel())
        all_zs.append(np.column_stack([z0, z1, nan]).ravel())

    if not all_xs:
        return np.array([]), np.array([])
    return np.concatenate(all_xs), np.concatenate(all_zs)


def _region_centroids_ly(stride: int = 4) -> list[tuple[str, float, float]]:
    """List of (name, x_ly, z_ly) for each region's pixel centroid."""
    from edda.analysis._region_map_data import regions as _names
    bm = _get_region_bm(stride)
    sc = _REG_PX_SZ * stride
    result = []
    for rid in range(1, 43):
        pz, px = np.where(bm == rid)
        if len(px) == 0:
            continue
        result.append((_names[rid], float(px.mean()) * sc + _REG_X0,
                       float(pz.mean()) * sc + _REG_Z0))
    return result


def _overlay_regions_2d(ax) -> None:
    """Overlay region boundary image + name labels on a matplotlib X/Z axis."""
    bm    = _get_region_bm(stride=1)
    named = bm > 0
    bnd   = np.zeros(bm.shape, dtype=bool)
    bnd[:-1, :] |= (bm[:-1, :] != bm[1:, :]) & (named[:-1, :] | named[1:, :])
    bnd[:, :-1] |= (bm[:, :-1] != bm[:, 1:]) & (named[:, :-1] | named[:, 1:])
    rgba      = np.zeros((*bm.shape, 4), dtype=np.float32)
    rgba[bnd] = [0.55, 0.55, 0.55, 0.50]
    # extent: [left, right, bottom, top] in data coords; origin='lower' → row 0 = bottom
    ax.imshow(rgba,
              extent=[_REG_X0, _REG_X_MAX, _REG_Z0, _REG_Z_MAX],
              origin="lower", aspect="auto", zorder=3, interpolation="bilinear")
    for name, x_ly, z_ly in _region_centroids_ly(stride=4):
        ax.text(x_ly, z_ly, name, color="#aaaaaa", fontsize=4.5, alpha=0.55,
                ha="center", va="center", zorder=4, fontweight="bold")


_REGION_LEGENDGROUP  = "Regions"
# Full spatial extent of the 2048-pixel region bitmap in game coordinates
_REG_X_MAX = _REG_X0 + 2048 * _REG_PX_SZ   # ≈ +51,155 ly
_REG_Z_MAX = _REG_Z0 + 2048 * _REG_PX_SZ   # ≈ +77,075 ly



def _region_boundary_trace_2d() -> go.Scatter:
    """Scatter trace with region boundary markers for a toggleable 2-D X/Z legend entry."""
    xs, zs = _region_boundary_px_coords(stride=3)
    return go.Scatter(
        x=xs.tolist(), y=zs.tolist(),
        mode="markers",
        marker=dict(size=1, color="rgba(140,140,140,0.50)", symbol="square"),
        hoverinfo="skip", showlegend=True,
        legendgroup="Regions",
        legendgrouptitle=dict(text=_REGION_LEGENDGROUP, font=dict(color="white", size=11)),
        name="Region boundaries",
    )


def _region_label_trace_2d() -> go.Scatter:
    """Scatter trace with region name labels for a 2-D X/Z map."""
    c = _region_centroids_ly(stride=4)
    return go.Scatter(
        x=[v[1] for v in c], y=[v[2] for v in c],
        mode="text", text=[v[0] for v in c],
        textfont=dict(color="rgba(180,180,180,0.55)", size=9),
        hoverinfo="skip", showlegend=True,
        legendgroup="Regions",
        name="Region labels",
    )


def _region_boundary_px_coords(stride: int) -> tuple[np.ndarray, np.ndarray]:
    """(xs_ly, zs_ly) of boundary pixel centres. One pixel per boundary edge side."""
    bm    = _get_region_bm(stride)
    sc    = _REG_PX_SZ * stride
    named = bm > 0
    bnd   = np.zeros(bm.shape, dtype=bool)
    bnd[:-1, :] |= (bm[:-1, :] != bm[1:, :]) & (named[:-1, :] | named[1:, :])
    bnd[:, :-1] |= (bm[:, :-1] != bm[:, 1:]) & (named[:, :-1] | named[:, 1:])
    pz, px = np.where(bnd)
    return px.astype(float) * sc + _REG_X0, pz.astype(float) * sc + _REG_Z0


def _region_traces_3d(y_plane: float = 0.0) -> list:
    """
    Scatter3d marker traces for region boundaries + labels on the galactic plane.
    Uses pixel markers at stride=1 (49 ly spacing) so that adjacent dots are
    sub-pixel at galaxy scale and appear as a solid continuous line.
    """
    xs, zs    = _region_boundary_px_coords(stride=1)
    ys        = np.full(len(xs), y_plane)
    centroids = _region_centroids_ly(stride=4)
    return [
        go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="markers",
            marker=dict(size=1.5, color="rgba(140,140,140,0.50)", symbol="square"),
            hoverinfo="skip", showlegend=True,
            name="Region boundaries",
            legendgroup="Regions",
            legendgrouptitle=dict(text="Regions", font=dict(color="white", size=11)),
        ),
        go.Scatter3d(
            x=[c[1] for c in centroids],
            y=[y_plane] * len(centroids),
            z=[c[2] for c in centroids],
            mode="text", text=[c[0] for c in centroids],
            textfont=dict(color="rgba(180,180,180,0.55)", size=9),
            hoverinfo="skip", showlegend=True,
            name="Region labels",
            legendgroup="Regions",
        ),
    ]


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

    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    _overlay_regions_2d(ax)
    ax.set_xlim(xlim); ax.set_ylim(ylim)
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
            groupclick="toggleitem",
            bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1,
        ),
    )
    fig.add_trace(_region_boundary_trace_2d())
    fig.add_trace(_region_label_trace_2d())
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
    intensity = np.repeat(log_counts, 8, axis=0)

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
    fig = go.Figure(data=[cube_trace] + _region_traces_3d() + [_landmark_trace_3d()] + extra)
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
                    groupclick="toggleitem",
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
                    groupclick="toggleitem",
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
    intensity = np.repeat(plot_df[metric].to_numpy(), 8, axis=0)

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
    fig = go.Figure(data=[cube_trace] + _region_traces_3d() + [_landmark_trace_3d()] + extra)
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
                    groupclick="toggleitem",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Combined sector 3D map — all rate layers in one figure with toggle buttons
# ---------------------------------------------------------------------------

def plot_sector_combined_3d(
    df_heat: pd.DataFrame,
    df_rates: pd.DataFrame,
    out_path: Path | None = None,
    current_pos: dict | None = None,
) -> go.Figure | None:
    """
    Single interactive 3D figure with four toggleable data layers:
      - Sector Heat Map (log₁₀ system count, Plasma)
      - Terraformable Rate (per visited system, YlOrRd)
      - Earth-like Rate (Reds)
      - Bio-signal Rate (YlGn)

    Layer buttons appear above the chart. Region boundaries and landmarks
    are always visible.
    """
    if df_heat.empty and df_rates.empty:
        return None

    data_traces: list[go.Mesh3d] = []
    layer_titles: list[str] = []

    _cbar = dict(tickfont=dict(color="white"),
                 title=dict(font=dict(color="white"), side="right"))

    # Layer 0: sector heat map
    if not df_heat.empty:
        x, y, z, fi, fj, fk, intensity = _build_cube_mesh(df_heat)
        custom = np.column_stack([
            df_heat["sector"].to_numpy(),
            df_heat["system_count"].to_numpy().astype(str),
            df_heat["grid_cx"].to_numpy().astype(int).astype(str),
            df_heat["grid_cy"].to_numpy().astype(int).astype(str),
            df_heat["grid_cz"].to_numpy().astype(int).astype(str),
        ])
        cbar = {**_cbar, "title": {**_cbar["title"], "text": "log₁₀(systems)"}}
        data_traces.append(go.Mesh3d(
            x=x, y=y, z=z, i=fi, j=fj, k=fk,
            intensity=intensity, colorscale="Plasma",
            colorbar=cbar,
            opacity=0.75,
            customdata=np.repeat(custom, 8, axis=0),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Systems visited: %{customdata[1]}<br>"
                "Grid centre: (%{customdata[2]}, %{customdata[3]}, %{customdata[4]}) ly"
                "<extra></extra>"
            ),
            name="Sector Heat Map", showscale=True, flatshading=True,
            visible=True, showlegend=True,
        ))
        layer_titles.append(
            f"Elite Dangerous — Sector Heat Map  ({len(df_heat):,} sectors, 1200 ly cubes)"
        )

    # Layers 1–3: rate maps
    _rate_layers = [
        ("terra_rate", "Terraformable rate", "YlOrRd"),
        ("elw_rate",   "Earth-like rate",    "Reds"),
        ("bio_rate",   "Bio-signal rate",    "YlGn"),
    ]
    for metric, label, colorscale in _rate_layers:
        if df_rates.empty or metric not in df_rates.columns:
            continue
        plot_df = df_rates[(df_rates["system_count"] >= 3) & (df_rates[metric] > 0)].copy()
        if plot_df.empty:
            continue
        x, y, z, fi, fj, fk, _ = _build_cube_mesh(plot_df)
        intensity_r = np.repeat(plot_df[metric].to_numpy(), 8, axis=0)
        count_col = metric.replace("_rate", "_count")
        count_vals = (plot_df[count_col].to_numpy()
                      if count_col in plot_df.columns else np.zeros(len(plot_df)))
        custom = np.column_stack([
            plot_df["sector"].to_numpy(),
            plot_df["system_count"].to_numpy().astype(str),
            plot_df[metric].to_numpy().round(4).astype(str),
            count_vals.astype(int).astype(str),
        ])
        cbar = {**_cbar, "title": {**_cbar["title"], "text": label}}
        data_traces.append(go.Mesh3d(
            x=x, y=y, z=z, i=fi, j=fj, k=fk,
            intensity=intensity_r, colorscale=colorscale,
            colorbar=cbar,
            opacity=0.80,
            customdata=np.repeat(custom, 8, axis=0),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"{label}: %{{customdata[2]}}<br>"
                "Bodies: %{customdata[3]}<br>"
                "Systems visited: %{customdata[1]}"
                "<extra></extra>"
            ),
            name=label, showscale=True, flatshading=True,
            visible="legendonly", showlegend=True,
        ))
        layer_titles.append(
            f"Elite Dangerous — {label}  ({len(plot_df):,} sectors, 1200 ly cubes)"
        )

    if not data_traces:
        return None

    n_data = len(data_traces)
    region_traces = _region_traces_3d()
    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []

    all_traces = data_traces + region_traces + [_landmark_trace_3d()] + extra

    fig = go.Figure(data=all_traces)
    fig.update_layout(
        title=dict(
            text=layer_titles[0],
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
                    groupclick="toggleitem",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig, n_data, layer_titles
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# High-value exobiology combined 3D map — all species as toggleable layers
# ---------------------------------------------------------------------------

# 24-color qualitative palette, visually distinct at galaxy scale
_EXOBIO_COLORS = [
    "#2E91E5", "#E15F99", "#1CA71C", "#FB0D0D", "#DA16FF",
    "#B68100", "#750D86", "#EB663B", "#511CFB", "#00A08B",
    "#FB00D1", "#FC0080", "#B2828D", "#6C7C32", "#778AAE",
    "#862A16", "#A777F1", "#620042", "#1616A7", "#DA60CA",
    "#6C4516", "#0D2A63", "#AF0038", "#222A2A",
]


def plot_exobio_combined_3d(
    species_data: list[tuple[str, pd.DataFrame]],
    out_path: Path | None = None,
    current_pos: dict | None = None,
) -> go.Figure | None:
    """
    Combined 3D galaxy map for high-value exobiology species.

    Each species is a separate Scatter3d trace (one per layer).  The first
    species is visible by default; the rest are legend-only so the user can
    click legend entries to show/hide individual species.

    species_data  — [(species_name, df), ...] sorted value-descending.
                    Each df must have columns: x, y, z, system_name, scan_count.
    """
    species_data = [(sp, df) for sp, df in species_data if not df.empty]
    if not species_data:
        return None

    traces: list[go.Scatter3d] = []
    for i, (species, df) in enumerate(species_data):
        color: str = _EXOBIO_COLORS[i % len(_EXOBIO_COLORS)]
        visible: bool | str = True if i == 0 else "legendonly"
        # Sort ascending so the first element (used by Plotly for the legend dot)
        # is always the minimum size → uniform legend dots across all species.
        df_s = df.sort_values("scan_count")
        counts = df_s["scan_count"].to_numpy(dtype=float).clip(min=1)
        sizes = (8 + (counts - 1) * 4).tolist()   # 1 scan→8px, 6→28px, 8→36px …
        traces.append(go.Scatter3d(
            x=df_s["x"].tolist(),
            y=df_s["y"].tolist(),
            z=df_s["z"].tolist(),
            mode="markers",
            marker=dict(size=sizes, color=color, opacity=0.85, line=dict(width=0)),
            text=df_s["system_name"].tolist(),
            customdata=df_s["scan_count"].astype(int).tolist(),
            hovertemplate=(
                f"<b>%{{text}}</b><br>"
                f"{species}<br>"
                f"Scans: %{{customdata}}<br>"
                f"(%{{x:.1f}}, %{{y:.1f}}, %{{z:.1f}}) ly"
                f"<extra></extra>"
            ),
            name=species,
            visible=visible,
            legendgroup="Species",
            legendgrouptitle=(
                dict(text="Species", font=dict(color="white", size=11)) if i == 0 else None
            ),
        ))

    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []
    n_sp  = len(species_data)
    n_sys = sum(len(df) for _, df in species_data)

    # Species first → top of legend; regions/landmarks last → bottom of legend
    fig = go.Figure(data=traces + _region_traces_3d() + [_landmark_trace_3d()] + extra)
    fig.update_layout(
        title=dict(
            text=f"High-Value Exobiology — {n_sp} species, {n_sys:,} systems total",
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
            camera=dict(eye=dict(x=0.0, y=1.2, z=-1.8), up=dict(x=0, y=1, z=0)),
        ),
        paper_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            groupclick="toggleitem",
            bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1,
        ),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# NSP 3D scatter map
# ---------------------------------------------------------------------------

# Hue (degrees) for each NSP category; subcategory shades vary lightness.
_NSP_CAT_SHORT: dict[str, str] = {
    "Lagrange Clouds":    "Clouds",
    "Mineral Formations": "Minerals",
    "Seed Pods":          "Pods",
}

_NSP_CATEGORY_HUES: dict[str, tuple[int, float]] = {
    # (hue_degrees, saturation)
    "Anomalies":          (35,  0.90),
    "Lagrange Clouds":    (195, 0.90),
    "Mineral Formations": (215, 0.45),
    "Molluscs":           (230, 0.75),
    "Plants":             (130, 0.65),
    "Seed Pods":          (285, 0.70),
    "Other":              (0,   0.50),
}


def _nsp_color(category: str, subcat_idx: int, subcat_total: int) -> str:
    """Hex colour for a subcategory: same hue as category, lightness varies."""
    hue_deg, sat = _NSP_CATEGORY_HUES.get(category, (0, 0.50))
    lightness = 0.42 + 0.28 * (subcat_idx / max(subcat_total - 1, 1))
    r, g, b = colorsys.hls_to_rgb(hue_deg / 360.0, lightness, sat)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def plot_nsp_map_3d(df_codex: pd.DataFrame,
                    out_path: Path | None = None,
                    current_pos: dict | None = None) -> go.Figure | None:
    """
    3D galaxy map of NSP codex discoveries.
    Expects df_codex to carry 'nsp_cat' and 'nsp_subcat' columns
    (added by dashboard._build_nsp_section before calling here).
    """
    if df_codex.empty:
        return None
    if "nsp_cat" not in df_codex.columns or "nsp_subcat" not in df_codex.columns:
        return None

    df = (df_codex
          .drop_duplicates(subset=["system_address", "nsp_subcat"])
          .sort_values(["nsp_cat", "nsp_subcat"])
          .copy())

    # Pre-compute per-category subcategory ordering for shade assignment
    cat_subcat_order: dict[str, list[str]] = {
        cat: sorted(grp["nsp_subcat"].unique())
        for cat, grp in df.groupby("nsp_cat")
    }

    traces = []
    for (cat, subcat), grp in df.groupby(["nsp_cat", "nsp_subcat"]):
        subcats = cat_subcat_order.get(cat, [subcat])
        idx = subcats.index(subcat) if subcat in subcats else 0
        color = _nsp_color(cat, idx, len(subcats))

        sys_names = (grp["system_name"].tolist()
                     if "system_name" in grp.columns else [""] * len(grp))
        cat_s = str(cat)
        group_key = _NSP_CAT_SHORT.get(cat_s, cat_s.replace(" ", ""))
        traces.append(go.Scatter3d(
            x=grp["x"].tolist(), y=grp["y"].tolist(), z=grp["z"].tolist(),
            mode="markers",
            marker=dict(size=7, color=color, opacity=0.85, line=dict(width=0)),
            text=sys_names,
            hovertemplate=(
                "<b>%{text}</b><br>"
                f"{subcat}<br>"
                "(%{x:.1f}, %{y:.1f}, %{z:.1f}) ly"
                "<extra></extra>"
            ),
            name=subcat,
            legendgroup=group_key,
            legendgrouptitle=dict(text=group_key, font=dict(color="white", size=11)),
        ))

    extra = [_current_pos_trace_3d(current_pos)] if current_pos else []
    n_sys = df["system_address"].nunique()
    fig = go.Figure(data=_region_traces_3d() + traces + [_landmark_trace_3d()] + extra)
    fig.update_layout(
        title=dict(
            text=f"Notable Stellar Phenomena — Galaxy Map ({n_sys:,} systems)",
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
            camera=dict(eye=dict(x=0.0, y=1.2, z=-1.8), up=dict(x=0, y=1, z=0)),
        ),
        paper_bgcolor="#0a0a1a",
        font_color="white",
        width=1400, height=900,
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top",
                    groupclick="toggleitem",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466",
                    borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None


# ---------------------------------------------------------------------------
# Trip route map
# ---------------------------------------------------------------------------

def plot_trip_route_3d(
    df_route: pd.DataFrame,
    df_systems: pd.DataFrame,
    out_path: Path | None = None,
) -> go.Figure | None:
    """
    Interactive 3D galaxy-scale route map for a trip report.

    df_route   — stats.trip_route_points(): jumps in order, columns incl. x/y/z.
                 Used for the route line and start/end markers.
    df_systems — stats.trip_system_data(): per-system aggregates, columns:
                 name, x, y, z, est_total, bio_signals_total, bodies_mapped.

    Layers (top → bottom of legend):
      Route            — line connecting systems in jump order
      Est. system value — bubble size ∝ sqrt(exploration + bio value)
      Bio signals      — bubble size ∝ signal count (only systems > 0)
      Mapped bodies    — bubble size ∝ mapped count  (legendonly)
      Start / End      — square markers
      Regions          — galaxy region boundaries (legendonly)
      Landmarks        — named landmarks
    """
    if df_route.empty:
        return None
    df_r = df_route.dropna(subset=["x", "y", "z"]).copy()
    if df_r.empty:
        return None

    traces: list[go.Scatter3d] = []

    # --- Route line ---
    traces.append(go.Scatter3d(
        x=df_r["x"].tolist(), y=df_r["y"].tolist(), z=df_r["z"].tolist(),
        mode="lines",
        line=dict(color="#4488cc", width=2),
        name="Route",
        hoverinfo="skip",
    ))

    # --- Bubble layers (from per-system data) ---
    if not df_systems.empty:
        df_s = df_systems.dropna(subset=["x", "y", "z"]).copy()

        # Layer 1: Estimated system value (exploration + bio)
        if "est_total" in df_s.columns and df_s["est_total"].sum() > 0:
            df_v = df_s[df_s["est_total"] > 0].sort_values("est_total")
            max_val = float(df_v["est_total"].max()) or 1.0
            sizes_v = (4 + 16 * (df_v["est_total"] / max_val) ** 0.5).tolist()
            val_labels = df_v["est_total"].apply(
                lambda v: f"{v/1e6:.1f} MCr" if v >= 1e6 else f"{v/1e3:.0f} KCr"
            ).tolist()
            traces.append(go.Scatter3d(
                x=df_v["x"].tolist(), y=df_v["y"].tolist(), z=df_v["z"].tolist(),
                mode="markers",
                marker=dict(size=sizes_v, color="#ff9944", opacity=0.80,
                            line=dict(width=0)),
                text=df_v["name"].tolist(),
                customdata=val_labels,
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Est. value: %{customdata}<extra></extra>"
                ),
                name="Est. system value",
            ))

        # Layer 2: Bio signals
        if "bio_signals_total" in df_s.columns:
            df_bio = df_s[df_s["bio_signals_total"] > 0].sort_values("bio_signals_total")
            if not df_bio.empty:
                sizes_bio = (5 + df_bio["bio_signals_total"].clip(upper=8) * 2).tolist()
                traces.append(go.Scatter3d(
                    x=df_bio["x"].tolist(), y=df_bio["y"].tolist(), z=df_bio["z"].tolist(),
                    mode="markers",
                    marker=dict(size=sizes_bio, color="#44dd88", opacity=0.85,
                                line=dict(width=0)),
                    text=df_bio["name"].tolist(),
                    customdata=df_bio["bio_signals_total"].astype(int).tolist(),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "Bio signals: %{customdata}<extra></extra>"
                    ),
                    name="Bio signals",
                ))

        # Layer 3: Mapped bodies (legendonly)
        if "bodies_mapped" in df_s.columns:
            df_map = df_s[df_s["bodies_mapped"] > 0].sort_values("bodies_mapped")
            if not df_map.empty:
                sizes_map = (5 + (df_map["bodies_mapped"].clip(upper=15) * 1.2)).tolist()
                traces.append(go.Scatter3d(
                    x=df_map["x"].tolist(), y=df_map["y"].tolist(), z=df_map["z"].tolist(),
                    mode="markers",
                    marker=dict(size=sizes_map, color="#88ccff", opacity=0.75,
                                line=dict(width=0)),
                    text=df_map["name"].tolist(),
                    customdata=df_map["bodies_mapped"].astype(int).tolist(),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "Mapped bodies: %{customdata}<extra></extra>"
                    ),
                    name="Mapped bodies",
                    visible="legendonly",
                ))

    # --- Start / end markers ---
    start, end = df_r.iloc[0], df_r.iloc[-1]
    traces.append(go.Scatter3d(
        x=[start["x"], end["x"]], y=[start["y"], end["y"]], z=[start["z"], end["z"]],
        mode="markers+text",
        marker=dict(size=8, color=["#44ff44", "#ff4444"], opacity=1.0,
                    symbol="square", line=dict(width=0)),
        text=[start["name"][:24], end["name"][:24]],
        textposition=["top center", "top center"],
        textfont=dict(size=9, color="white"),
        name="Start / End",
        hoverinfo="skip",
    ))

    # --- Regions + landmarks (same as other dashboard maps) ---
    n_sys = len(df_r)
    fig = go.Figure(data=traces + _region_traces_3d() + [_landmark_trace_3d()])
    fig.update_layout(
        title=dict(text=f"Route — {n_sys:,} systems", font=dict(color="white")),
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
            camera=dict(eye=dict(x=0.0, y=1.2, z=-1.8), up=dict(x=0, y=1, z=0)),
        ),
        paper_bgcolor="#0a0a1a", font_color="white",
        width=1400, height=900,
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top",
                    groupclick="toggleitem",
                    bgcolor="rgba(10,10,30,0.8)", bordercolor="#444466", borderwidth=1),
    )

    if out_path is None:
        return fig
    _write_interactive(fig, out_path)
    return None

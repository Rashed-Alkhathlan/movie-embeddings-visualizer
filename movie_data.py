"""Standalone movie data + vector-search layer.

Side-effect-free: imports only numpy/pandas/scipy. No Flask, no chatbot, no
`app` package. Both the Flask app (via app.services) and the database MCP
server import from here, so the search logic has a single source of truth and
can be loaded by a stdio subprocess without dragging in the web app.

Data is loaded lazily on first use and cached for the lifetime of the process.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from scipy.spatial import KDTree

# ---------------------------------------------------------------------------
# Lazy data store
# ---------------------------------------------------------------------------

_DF: pd.DataFrame | None = None
_COORDS = None
_TREE: KDTree | None = None


def _data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "processed" / "with_embeddings.csv"


def get_data() -> Tuple[pd.DataFrame, object, KDTree]:
    """Return the cached (df, coords, tree), loading + building them on first call."""
    global _DF, _COORDS, _TREE

    if _DF is None:
        _DF = pd.read_csv(_data_path())

    if _COORDS is None:
        _COORDS = _DF[["x", "y", "z"]].values

    if _TREE is None:
        _TREE = KDTree(_COORDS)

    return _DF, _COORDS, _TREE


# ---------------------------------------------------------------------------
# Matching / scaling helpers
# ---------------------------------------------------------------------------


def find_movie_match(df, movie_name: str):
    movie_name_str = str(movie_name).strip()

    # Check if format is "Movie Name (Year)"
    match_with_year = re.match(r'^(.*)\s+\(([^)]+)\)$', movie_name_str)

    if match_with_year:
        name_part = match_with_year.group(1).strip()
        year_part = match_with_year.group(2).strip()

        # Filter by name first
        matches = df[df["names"].str.strip().str.lower() == name_part.lower()]

        if not matches.empty:
            # If multiple, check year
            for idx, row in matches.iterrows():
                date_val = row.get("date_x")
                if pd.isna(date_val):
                    year = "Unknown Year"
                else:
                    date_str = str(date_val).strip()
                    year = date_str.split('/')[-1] if date_str else "Unknown Year"

                if year == year_part:
                    return df.loc[[idx]]

            # If no year matches exactly, return first match
            return matches.iloc[[0]]

        # fallback to partial name match
        partial = df[df["names"].str.strip().str.lower().str.contains(name_part.lower(), regex=False)]
        if not partial.empty:
            for idx, row in partial.iterrows():
                date_val = row.get("date_x")
                if pd.isna(date_val):
                    year = "Unknown Year"
                else:
                    date_str = str(date_val).strip()
                    year = date_str.split('/')[-1] if date_str else "Unknown Year"

                if year == year_part:
                    return df.loc[[idx]]

            return partial.iloc[[0]]

        return None

    # Original logic without year
    match = df[df["names"].str.strip().str.lower() == movie_name_str.lower()]
    if match.empty:
        partial = df[df["names"].str.strip().str.lower().str.contains(movie_name_str.lower(), regex=False)]
        if partial.empty:
            return None
        match = partial.iloc[[0]]
    return match


def scale_vectors(neighbors):
    rel_vectors = np.array([[n["rel"]["x"], n["rel"]["y"], n["rel"]["z"]] for n in neighbors], dtype=float)
    max_abs = float(np.max(np.abs(rel_vectors))) if rel_vectors.size else 1.0
    scale = 1.0 if max_abs == 0 else 120.0 / max_abs

    for item in neighbors:
        item["render"] = {
            "x": item["rel"]["x"] * scale,
            "y": item["rel"]["y"] * scale,
            "z": item["rel"]["z"] * scale,
        }

    return neighbors


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------


def get_autocomplete_suggestions(query, limit=10):
    df, _coords, _tree = get_data()
    q = query.strip().lower()
    if not q:
        return []

    matches_df = df[df["names"].str.strip().str.lower().str.contains(q, regex=False)]

    suggestions = []
    for _, row in matches_df.head(limit).iterrows():
        name = row["names"]
        date_val = row.get("date_x")
        if pd.isna(date_val):
            year = "Unknown Year"
        else:
            date_str = str(date_val).strip()
            year = date_str.split('/')[-1] if date_str else "Unknown Year"
        suggestions.append(f"{name} ({year})")

    return suggestions


def get_closest_movies(movie_name, n=5):
    df, coords, tree = get_data()
    match = find_movie_match(df, movie_name)
    if match is None:
        return None, None

    idx = int(match.index[0])
    target_xyz = np.asarray(coords[idx], dtype=float)
    _distances, indices = tree.query(target_xyz, k=n + 1)
    neighbor_indices = np.atleast_1d(indices)[1:].astype(int)

    results = df.iloc[neighbor_indices][["names", "genre", "score", "overview", "date_x"]].copy()

    # Add year to the titles in results and the main match
    results['title'] = results.apply(
        lambda row: f'{row["names"]} ({str(row["date_x"]).strip().split("/")[-1] if pd.notna(row["date_x"]) and str(row["date_x"]).strip() else "Unknown Year"})',
        axis=1
    )
    results = results.drop(columns=["names"]).rename(columns={"date_x": "release_date"})

    match_row = match.iloc[0]
    date_val = match_row.get("date_x")
    if pd.isna(date_val):
        year = "Unknown Year"
    else:
        date_str = str(date_val).strip()
        year = date_str.split('/')[-1] if date_str else "Unknown Year"
    match_title_with_year = f'{match_row["names"]} ({year})'

    return match_title_with_year, results.to_dict(orient="records")


def get_movie_graph(movie_name, n=25):
    df, coords, tree = get_data()
    match = find_movie_match(df, movie_name)
    if match is None:
        return None, None

    center_idx = int(match.index[0])
    center_row = df.iloc[center_idx]
    center_xyz = np.asarray(coords[center_idx], dtype=float)

    distances, indices = tree.query(center_xyz, k=n + 1)
    neighbor_indices = np.atleast_1d(indices)[1:].astype(int)
    neighbor_distances = np.atleast_1d(distances)[1:].astype(float)

    neighbors = []
    for rank, (idx, distance) in enumerate(zip(neighbor_indices, neighbor_distances), start=1):
        row = df.iloc[int(idx)]
        point = np.asarray(coords[int(idx)], dtype=float)
        rel = point - center_xyz

        date_val = row.get("date_x")
        if pd.isna(date_val):
            year = "Unknown Year"
        else:
            date_str = str(date_val).strip()
            year = date_str.split('/')[-1] if date_str else "Unknown Year"
        title_with_year = f'{row["names"]} ({year})'

        neighbors.append(
            {
                "rank": int(rank),
                "is_primary": bool(rank <= 5),
                "title": title_with_year,
                "genre": row.get("genre", "Unknown"),
                "score": row.get("score", None),
                "release_date": row.get("date_x", ""),
                "overview": row.get("overview", ""),
                "distance": float(distance),
                "xyz": {"x": float(point[0]), "y": float(point[1]), "z": float(point[2])},
                "rel": {"x": float(rel[0]), "y": float(rel[1]), "z": float(rel[2])},
            }
        )

    neighbors = scale_vectors(neighbors)

    center_date_val = center_row.get("date_x")
    if pd.isna(center_date_val):
        center_year = "Unknown Year"
    else:
        center_date_str = str(center_date_val).strip()
        center_year = center_date_str.split('/')[-1] if center_date_str else "Unknown Year"
    center_title_with_year = f'{center_row["names"]} ({center_year})'

    center = {
        "title": center_title_with_year,
        "genre": center_row.get("genre", "Unknown"),
        "score": center_row.get("score", None),
        "release_date": center_row.get("date_x", ""),
        "overview": center_row.get("overview", ""),
        "xyz": {"x": float(center_xyz[0]), "y": float(center_xyz[1]), "z": float(center_xyz[2])},
    }

    return center, neighbors

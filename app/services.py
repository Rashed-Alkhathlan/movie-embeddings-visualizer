from app import df, coords, tree
from app.utils import find_movie_match, scale_vectors
import numpy as np

def get_autocomplete_suggestions(query, limit=10):
    q = query.strip().lower()
    if not q:
        return []
    matches = df[df["names"].str.strip().str.lower().str.contains(q, regex=False)]["names"].dropna().tolist()
    return matches[:limit]


def get_closest_movies(movie_name, n=5):
    match = find_movie_match(df, movie_name)
    if match is None:
        return None, None

    idx = int(match.index[0])
    target_xyz = np.asarray(coords[idx], dtype=float)
    _distances, indices = tree.query(target_xyz, k=n + 1)
    neighbor_indices = np.atleast_1d(indices)[1:].astype(int)

    results = df.iloc[neighbor_indices][["names", "genre", "score", "overview", "date_x"]].copy()
    results = results.rename(columns={"names": "title", "date_x": "release_date"})
    return match.iloc[0]["names"], results.to_dict(orient="records")


def get_movie_graph(movie_name, n=25):
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
        neighbors.append(
            {
                "rank": int(rank),
                "is_primary": bool(rank <= 5),
                "title": row["names"],
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

    center = {
        "title": center_row["names"],
        "genre": center_row.get("genre", "Unknown"),
        "score": center_row.get("score", None),
        "release_date": center_row.get("date_x", ""),
        "overview": center_row.get("overview", ""),
        "xyz": {"x": float(center_xyz[0]), "y": float(center_xyz[1]), "z": float(center_xyz[2])},
    }

    return center, neighbors
from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
from scipy.spatial import KDTree
import numpy as np

app = Flask(__name__, static_folder="static")

df = pd.read_csv("with_embeddings.csv")
coords = df[["x", "y", "z"]].values
tree = KDTree(coords)


def find_movie_match(movie_name):
    match = df[df["names"].str.strip().str.lower() == movie_name.strip().lower()]
    if match.empty:
        partial = df[df["names"].str.strip().str.lower().str.contains(movie_name.strip().lower(), regex=False)]
        if partial.empty:
            return None
        match = partial.iloc[[0]]
    return match


def get_closest_movies(movie_name, n=5):
    match = find_movie_match(movie_name)
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
    match = find_movie_match(movie_name)
    if match is None:
        return None

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
                "xyz": {
                    "x": float(point[0]),
                    "y": float(point[1]),
                    "z": float(point[2]),
                },
                "rel": {
                    "x": float(rel[0]),
                    "y": float(rel[1]),
                    "z": float(rel[2]),
                },
            }
        )

    rel_vectors = np.array([[n["rel"]["x"], n["rel"]["y"], n["rel"]["z"]] for n in neighbors], dtype=float)
    max_abs = float(np.max(np.abs(rel_vectors))) if rel_vectors.size else 1.0
    scale = 1.0 if max_abs == 0 else 120.0 / max_abs

    for item in neighbors:
        item["render"] = {
            "x": item["rel"]["x"] * scale,
            "y": item["rel"]["y"] * scale,
            "z": item["rel"]["z"] * scale,
        }

    center = {
        "title": center_row["names"],
        "genre": center_row.get("genre", "Unknown"),
        "score": center_row.get("score", None),
        "release_date": center_row.get("date_x", ""),
        "overview": center_row.get("overview", ""),
        "xyz": {
            "x": float(center_xyz[0]),
            "y": float(center_xyz[1]),
            "z": float(center_xyz[2]),
        },
    }

    return {"center": center, "neighbors": neighbors}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    found_title, results = get_closest_movies(query)
    if results is None:
        return jsonify({"error": f"No movie found matching '{query}'"}), 404

    return jsonify({"query": found_title, "results": results})


@app.route("/autocomplete")
def autocomplete():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])
    matches = df[df["names"].str.strip().str.lower().str.contains(q, regex=False)]["names"].dropna().unique().tolist()
    return jsonify(matches[:10])


@app.route("/graph")
def graph():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    n_raw = request.args.get("n", "25").strip()
    try:
        n = int(n_raw)
    except ValueError:
        n = 25
    n = max(5, min(n, 50))

    graph_payload = get_movie_graph(query, n=n)
    if graph_payload is None:
        return jsonify({"error": f"No movie found matching '{query}'"}), 404

    return jsonify(graph_payload)


if __name__ == "__main__":
    app.run(debug=True, port=5000)

from flask import request, jsonify, render_template
from app import app
from app.services import get_closest_movies, get_movie_graph, get_autocomplete_suggestions

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    found_title, results = get_closest_movies(query)
    if results is None:
        return jsonify({"error": f"No movie found matching '{query}'"}), 404

    return jsonify({
        "query": found_title, 
        "results": results
    })


@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("q", "").strip()
    return jsonify(get_autocomplete_suggestions(query))


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
    n = max(5, min(n, 100))

    center, neighbors = get_movie_graph(query, n=n)
    if not center:
        return jsonify({"error": f"No movie found matching '{query}'"}), 404

    return jsonify({
        "center": center,
        "neighbors": neighbors
    })
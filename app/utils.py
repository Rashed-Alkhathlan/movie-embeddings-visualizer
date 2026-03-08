import requests
import numpy as np

def fetch_poster(movie: str):

    """
    fetches image url of given movie

    Args:
        movie (str): The name of the movie to search for.

    Returns:
        str: The URL of the poster image.
    """

    data = requests.get(
        "https://imdb.iamidiotareyoutoo.com/search",
        params={"q": movie}).json()

    poster = data["description"][0]["#IMG_POSTER"]
    return poster


def find_movie_match(df, movie_name: str):
    match = df[df["names"].str.strip().str.lower() == movie_name.strip().lower()]
    if match.empty:
        partial = df[df["names"].str.strip().str.lower().str.contains(movie_name.strip().lower(), regex=False)]
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
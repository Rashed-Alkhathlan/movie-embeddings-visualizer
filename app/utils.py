import requests
import numpy as np
import re
import pandas as pd


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
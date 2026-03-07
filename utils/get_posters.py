import requests

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

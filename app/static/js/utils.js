export async function fetchPoster(movie) {
    try {
        const url = `https://imdb.iamidiotareyoutoo.com/search?q=${encodeURIComponent(movie)}`;

        const res = await fetch(url);
        const data = await res.json();

        const poster = data?.description?.[0]?.["#IMG_POSTER"];

        return poster || null;

    } catch (err) {
        return null;
    }
}
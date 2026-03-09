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

export function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
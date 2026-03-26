export async function fetchPoster(movie) {
    const { title, year } = parseMovie(movie);

    const baseUrl = "http://www.omdbapi.com/";
    const apiKey = "df3d67a1";

    // Build year candidates
    const yearsToTry = year
        ? [year, Number(year) - 1, Number(year) + 1]
        : [null];

    // Try OMDb with different years
    for (const y of yearsToTry) {
        const url = `${baseUrl}?t=${encodeURIComponent(title)}${
            y ? `&y=${y}` : ""
        }&apikey=${apiKey}`;

        try {
            const res = await fetch(url);
            const data = await res.json();

            const poster = data?.Poster;
            if (poster && poster !== "N/A") {
                if (await isValidImage(poster)) {
                    return poster;
                }
            }
        } catch {}
    }

    // Fallback to IMDb
    try {
        const url2 = `https://imdb.iamidiotareyoutoo.com/search?q=${encodeURIComponent(movie)}`;
        const res2 = await fetch(url2);
        const data2 = await res2.json();

        const poster2 = data2?.description?.[0]?.["#IMG_POSTER"];
        if (poster2) {
            if (await isValidImage(poster2)) {
                return poster2;
            }
        }
    } catch {}

    return null;
}

function parseMovie(input) {
    const match = input.match(/^(.*?)(?:\s*\((\d{4})\))?$/);

    return {
        title: match?.[1]?.trim() || input,
        year: match?.[2] || null
    };
}

async function isValidImage(url) {
    try {
        const res = await fetch(url, { method: "HEAD" });
        return res.ok;
    } catch {
        return false;
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
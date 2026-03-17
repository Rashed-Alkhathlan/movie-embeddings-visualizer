import asyncio
import json
import queue
import threading
from flask import request, jsonify, render_template, Response, stream_with_context
from app import app, bot
from app.services import get_closest_movies, get_movie_graph, get_autocomplete_suggestions

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/chat")            # new GET route for the page
def chat_page():
    return render_template("chat.html")


@app.get("/search")
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


@app.get("/autocomplete")
def autocomplete():
    query = request.args.get("q", "").strip()
    return jsonify(get_autocomplete_suggestions(query))


@app.get("/graph")
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

bot_lock = threading.Lock()

@app.post("/api/chat")
def chat_bot():
    user_message = request.get_json().get("message", "")

    # Reject immediately if bot is busy
    if not bot_lock.acquire(blocking=False):
        return jsonify({
            "type": "error",
            "data": "The assistant is currently processing another request. Please wait."
        }), 429

    def generate():
        try:
            result_queue = queue.Queue()

            def run_stream():
                async def _run():
                    async for event_type, data in bot.ask_stream(user_message):
                        result_queue.put((event_type, data))
                asyncio.run(_run())

            threading.Thread(target=run_stream, daemon=True).start()

            while True:
                try:
                    event_type, data = result_queue.get(timeout=300)
                    yield f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"
                    if event_type in ("reply", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'error', 'data': 'Request timed out.'})}\n\n"
                    break
        finally:
            bot_lock.release()  # always release, even if something crashes

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/chat/history")
def clear_chat_history():
    bot.reset()
    return jsonify({"status": "success", "message": "Chat history cleared."})
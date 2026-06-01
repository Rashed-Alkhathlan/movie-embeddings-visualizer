import logging

from app import app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
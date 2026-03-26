from flask import Flask
from pathlib import Path
import pandas as pd
from scipy.spatial import KDTree
from models.chat_model import create_chatbot

app = Flask(__name__)

bot = create_chatbot()

# Load data once
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "processed" / "with_embeddings.csv"

df = pd.read_csv(DATA_PATH)
coords = df[["x", "y", "z"]].values
tree = KDTree(coords)

from app import routes

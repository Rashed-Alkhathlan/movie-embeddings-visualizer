from flask import Flask
import pandas as pd
from scipy.spatial import KDTree
from models.chat_model import create_chatbot

app = Flask(__name__)

bot = create_chatbot()

# Load data once
df = pd.read_csv("./data/processed/with_embeddings.csv")
coords = df[["x", "y", "z"]].values
tree = KDTree(coords)

from app import routes
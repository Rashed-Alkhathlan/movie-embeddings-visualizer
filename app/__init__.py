from flask import Flask
import pandas as pd
from scipy.spatial import KDTree

app = Flask(__name__)

# Load data once
df = pd.read_csv("./data/processed/with_embeddings.csv")
coords = df[["x", "y", "z"]].values
tree = KDTree(coords)

from app import routes
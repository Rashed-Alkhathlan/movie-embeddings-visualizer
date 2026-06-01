from flask import Flask
from models.chat_model import create_chatbot, AVAILABLE_MODELS

app = Flask(__name__)

bot = create_chatbot()

from app import routes

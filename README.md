# Movie Orbit
 
A Movie Embeddings Visualizer and an AI Assistant/Chatbot with tool calling.

###### **_For both Windows and Mac installations you have to have Python installed_**

## To run this on Windows
### Initialization:
1. Go to Google AI Studio and create an API key

2. Rename `.env.example` to `.env`

3. Inside the .env file on `GEMINI_API_KEY="your_api_key"` replace _your_api_key_ with the actual API key you got from Google AI Studio

---

### Virtual environment + Run:
1. `cd movie-embeddings-visualizer`

2. `python -m venv .venv`

3. `.venv\Scripts\Activate`

4. `pip install -r requirements.txt`

5. `python run.py`

The server will start on <http://localhost:5000/>

---

## To run this on Mac:
### Initialization:
1. Go to Google AI Studio and create an API key

2. Open a terminal on MacOS

3. Type `nano .zshrc`

4. At the bottom of the file, write `export GEMINI_API_KEY="your_api_key"` replace _your_api_key_ with the actual API key you got from Google AI Studio

5. Press `Ctrl o` to save then `Ctrl x ` to exit

---

### Virtual environment + Run:
1. `cd movie-embeddings-visualizer`

2. `conda create -n ml_proj python=3.12`

3. `conda activate ml_proj`

4. `pip install -r requirements_mac.txt`

5. `python run.py`

The server will start on <http://localhost:5000/>

---

### During development

To enable GPU utilization in the notebook (Nvidia Only), you'll have to uninstall the `torch` module, then reinstall it using the command from the [PyTorch website](https://pytorch.org/get-started/locally/) to activate appropriate CUDA support 

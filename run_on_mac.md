## To run this project on mac:
### Initialization:
1 - Go to google ai studio and create an api

2 - Open a terminal on MacOS

3 - Type `nano .zshrc`

4 - At the bottom of the file, write `export GEMINI_API_KEY="your_api_key"` replace _your_api_key_ with the actual api key you got from google ai studio

5 - press `ctrl o` to save and `ctrl x ` to exit

---

### Virtual environment + run
1 - `cd movie-embeddings-visualizer`

2 - `conda create -n ml_proj python=3.12`

3 - `conda activate ml_proj`

4 - `pip install -r requirements_mac.txt`

5 - `python run.py`
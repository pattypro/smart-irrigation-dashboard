# Smart Irrigation Dashboard

## How to Deploy

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd <repo-folder>
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run locally**:
   ```bash
   streamlit run app.py
   ```

4. **Deploy on Streamlit Cloud**:
   - Push all files to GitHub.
   - Go to [Streamlit Cloud](https://streamlit.io/cloud).
   - Create a new app and select your repo.
   - Set **Main file path** to `app.py`.
   - Deploy.

## Files Included
- `app.py`: Main dashboard app.
- `logic.py`: Irrigation decision logic.
- `data_io.py`: Google Sheets integration.
- `emailer.py`: Gmail API integration.
- `requirements.txt`: Python dependencies.

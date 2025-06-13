from fastapi import FastAPI, HTTPException
import json
from typing import Optional

app = FastAPI(title="Lottery History API")

def load_history():
    with open("history.json", "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Lottery History API"}

@app.get("/lottery")
def get_lottery(
    game: Optional[str] = None,
    date: Optional[str] = None
):
    """
    - /lottery                → returns entire JSON (timestamp + both games)
    - /lottery?game=powerball → returns just the powerball array
    - /lottery?game=megaMillions&date=2025-01-07
      → returns only the draw(s) matching that date
    """
    history = load_history()

    # if no specific game, return full history
    if not game:
        return history

    # normalize and validate
    key = game.strip()
    if key not in history:
        raise HTTPException(status_code=404, detail=f"Game '{game}' not found")

    entries = history[key]

    # filter by date if requested
    if date:
        filtered = [e for e in entries if e.get("date") == date]
        if not filtered:
            raise HTTPException(
                status_code=404,
                detail=f"No {key} draws found on {date}"
            )
        return filtered

    return entries

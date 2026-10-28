from fastapi import FastAPI
from app.routers import webhook

app = FastAPI(title="Bot Avance Checklist", version="1.0.0")

app.include_router(webhook.router)

@app.get("/")
async def root():
    return {"status": "online"}
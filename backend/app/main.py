from fastapi import FastAPI


app = FastAPI(title="PostForge API")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}

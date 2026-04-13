from fastapi import FastAPI

app = FastAPI(title="Multi-Tenant Inventory Validator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
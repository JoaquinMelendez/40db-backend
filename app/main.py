from fastapi import FastAPI

app = FastAPI()


@app.get("/hola-mundo")
def hola_mundo():
    return {"mensaje": "Hola Mundo"}

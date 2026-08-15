import uvicorn

from .api import create_app

app = create_app()


def run() -> None:
    uvicorn.run("research_workbench.main:app", host="0.0.0.0", port=8090, reload=False)


if __name__ == "__main__":
    run()

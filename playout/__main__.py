import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "playout.app:app",
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    main()

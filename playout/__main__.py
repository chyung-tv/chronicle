import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "playout.app:app",
        host=os.getenv("PLAYOUT_HOST", "0.0.0.0"),
        port=int(os.getenv("PLAYOUT_API_PORT") or os.getenv("PORT", "8765")),
        reload=False,
    )


if __name__ == "__main__":
    main()

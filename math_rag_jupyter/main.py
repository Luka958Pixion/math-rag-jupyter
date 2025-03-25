import uvicorn

from decouple import config

from math_rag_jupyter.endpoints import app


PORT = config('PORT', cast=int)

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT)

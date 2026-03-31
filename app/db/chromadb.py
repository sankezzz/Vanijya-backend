# app/db/chromadb.py
import os
import chromadb
from dotenv import load_dotenv

load_dotenv()

# Created ONCE when the app starts — reused for every request
_client = chromadb.HttpClient(
    ssl=True,
    host=os.getenv("CHROMA_HOST"),
    tenant=os.getenv("CHROMA_TENANT"),
    database=os.getenv("CHROMA_DATABASE"),
    headers={"x-chroma-token": os.getenv("CHROMA_API_KEY")}
)

_collection = _client.get_or_create_collection(
    name="commodity_users",
    metadata={"hnsw:space": "cosine"}
)

def get_chroma_collection():
    return _collection          # just returns the already-open collection

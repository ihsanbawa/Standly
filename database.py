from databases import Database
from dotenv import load_dotenv
import os

DATABASE_URL = os.environ['ZARATHUDB_URL']
database = Database(DATABASE_URL)

async def execute_query(query, values={}):
  try:
    return await database.execute(query, values)
  except Exception as e:
    print(f"Database query error: {e}")
    return None

# Helper function to fetch data from the database
async def fetch_query(query, values={}):
  try:
    return await database.fetch_all(query, values)
  except Exception as e:
    print(f"Database query error: {e}")
    return []
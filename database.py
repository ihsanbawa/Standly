from databases import Database
from dotenv import load_dotenv
import os

DATABASE_URL = os.environ['ZARATHUDB_URL']
database = Database(DATABASE_URL)

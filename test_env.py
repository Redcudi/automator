from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=".env")
print("APIFY_TOKEN:", os.getenv("APIFY_TOKEN"))
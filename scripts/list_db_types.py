"""Query the Appliku OpenAPI schema to find valid datastore store_type values.

Run from the repo root:
    python scripts/list_db_types.py
"""
import sys
from pathlib import Path

import requests
import yaml

API_KEY = None
TEAM_PATH = None

# Load from demo_project/.env.appliku
env_file = Path(__file__).parent.parent / "example" / "demo_project" / ".env.appliku"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.startswith("APPLIKU_API_KEY="):
            API_KEY = line.split("=", 1)[1].strip()
        elif line.startswith("APPLIKU_TEAM_PATH="):
            TEAM_PATH = line.split("=", 1)[1].strip()

if not API_KEY:
    sys.exit("APPLIKU_API_KEY not found in example/demo_project/.env.appliku")

BASE_URL = "https://api.appliku.com"
session = requests.Session()
session.headers.update({"Authorization": f"Token {API_KEY}"})

print("Fetching Appliku OpenAPI schema…")
resp = session.get(f"{BASE_URL}/api/schema/", headers={"Accept": "application/yaml"})
resp.raise_for_status()
schema = yaml.safe_load(resp.content)

# Navigate to DataStoreRequest → store_type enum
components = schema.get("components", {}).get("schemas", {})
ds = components.get("DataStoreRequest", {})
props = ds.get("properties", {})
# store_type uses a $ref to StoreTypeEnum
store_type_enum = components.get("StoreTypeEnum", {})
choices = store_type_enum.get("enum", [])

if choices:
    print("\nValid store_type values (StoreTypeEnum):")
    for c in choices:
        print(f"  {c}")
else:
    print("\nCould not find StoreTypeEnum — printing raw schema:")
    import json
    print(json.dumps(store_type_enum, indent=2))

import requests
from bs4 import BeautifulSoup
import json
import re
import os

URL = "https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
OUTPUT_FILE = os.path.join(DATA_DIR, "combinations.json")

def clean_text(text):
    if not text:
        return ""
    # Remove excessive whitespace
    return " ".join(text.split())

def fetch_combinations():
    print(f"Fetching {URL}...")
    try:
        response = requests.get(URL)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')

    # Mapping from header text (partial match) to json key
    header_mapping = {
        "Pasto completo": "pasto_completo",
        "Pasto ridotto con primo": "pasto_ridotto_a",
        "Pasto ridotto con secondo": "pasto_ridotto_b",
        "Pasto ridotto C": "pasto_ridotto_c"
    }

    # Find the table headers
    # We look for a table where the headers match our expectations
    tables = soup.find_all("table")
    target_table = None
    column_indices = {}

    for table in tables:
        headers = table.find_all(["th", "td"]) 
        # Sometimes headers are in the first row of cells (td or th)
        
        # Check first row explicitly
        rows = table.find_all("tr")
        if not rows:
            continue
            
        header_cells = rows[0].find_all(["th", "td"])
        
        # Check if this row looks like the header we want
        current_indices = {}
        found_matches_count = 0
        
        for idx, cell in enumerate(header_cells):
            text = clean_text(cell.get_text())
            for key, json_key in header_mapping.items():
                if key.lower() in text.lower():
                    current_indices[json_key] = idx
                    found_matches_count += 1
        
        # We need to ensure it's the specific table by checking for the long form headers
        # Pricing table only has "Pasto ridotto A", Definition table has "Pasto ridotto con primo (pasto ridotto A)"
        if "pasto_ridotto_a" in current_indices and "pasto_completo" in current_indices:
             target_table = table
             column_indices = current_indices
             break

    if not target_table:
        print("Could not find the table with meal combinations.")
        return

    print("Found table.")
    
    # Get the data row (should be the second row, index 1)
    rows = target_table.find_all("tr")
    if len(rows) < 2:
        print("Table does not have enough rows.")
        return

    data_row = rows[1]
    cells = data_row.find_all(["td", "th"])

    result = {}
    
    for json_key, idx in column_indices.items():
        if idx < len(cells):
            text = clean_text(cells[idx].get_text())
            if json_key == "pasto_completo":
                text = text.replace("TRADIZIONALE", "").strip()
            result[json_key] = text
        else:
            result[json_key] = None

    # Sort matching the user preference (if needed) or just dump
    # Ensure all keys are present even if not found (set to null or empty string)
    final_result = {
        "pasto_completo": result.get("pasto_completo", ""),
        "pasto_ridotto_a": result.get("pasto_ridotto_a", ""),
        "pasto_ridotto_b": result.get("pasto_ridotto_b", ""),
        "pasto_ridotto_c": result.get("pasto_ridotto_c", "")
    }

    print("Extracted Data:")
    print(json.dumps(final_result, indent=4, ensure_ascii=False))

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, indent=4, ensure_ascii=False)
    
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    fetch_combinations()

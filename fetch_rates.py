
import requests
from bs4 import BeautifulSoup
import json
import re

def clean_text(text):
    """Cleans text from whitespace and special characters"""
    # Replace non-breaking spaces and news lines
    text = text.replace('\xa0', ' ').replace('\n', ' ')
    # Replace multiple spaces/tabs with single space and strip
    return re.sub(r'\s+', ' ', text).strip()

def parse_money(money_str):
    """Parses money string to float. Returns 0.0 for 'gratuito'."""
    clean = clean_text(money_str).lower()
    if 'gratuito' in clean:
        return 0.0
    # Remove € and dots (thousands separator), replace comma with dot
    # Example: € 2.300,50 -> 2300.50
    # Example: € 2,80 -> 2.80
    # First remove '€' and spaces
    clean = re.sub(r'[€\s]', '', clean)
    # Remove dots (thousands)
    clean = clean.replace('.', '')
    # Replace comma with dot
    clean = clean.replace(',', '.')
    try:
        if not clean: return 0.0
        return float(clean)
    except ValueError:
        return 0.0 # Fallback

def parse_isee_range(isee_str):
    """Parses ISEE range string into min and max values."""
    clean = clean_text(isee_str).lower()
    
    # Handle scholarship holders
    if 'idonei' in clean or 'borsa di studio' in clean:
        # User wants "da che valore a che valore".
        # Let's represent this as 0 to 0 with a special flag if needed, 
        # or just 0.0 - 0.0 range which implies special logic in application.
        return {"min_isee": 0.0, "max_isee": 0.0, "scholarship": True}

    # Remove '€' and dots for easier parsing of thousands
    # But wait, 27.000 is 27000. So we remove dots.
    # What if it was decimal? Usually ISEE is integer or user standard locale.
    # The example data: "≤ € 27.000" -> 27000.
    
    clean_nums = clean.replace('.', '').replace('€', '')
    
    # Regex to find numbers. We might have ints or floats (with comma).
    # Since we removed dots, we assume commas are decimals.
    # However, in Italy 27.000 is 27k.
    # Let's clean spaces around symbols to make parsing easier
    
    # Extract all numbers
    numbers = re.findall(r'(\d+(?:,\d+)?)', clean_nums)
    # Convert to float
    parsed_numbers = []
    for n in numbers:
        n = n.replace(',', '.')
        parsed_numbers.append(float(n))
    
    min_val = 0.0
    max_val = float('inf') # Representing infinity
    
    # Analyze structure
    if '≤' in clean and '>' not in clean: 
        # ≤ € 27.000 => min 0, max 27000
        if parsed_numbers:
            max_val = parsed_numbers[0]
            
    elif '>' in clean and '≤' in clean:
        # > € 27.000 ≤ € 30.000
        if len(parsed_numbers) >= 2:
            min_val = parsed_numbers[0]
            max_val = parsed_numbers[1]
            
    elif '>' in clean and '≤' not in clean:
        # > € 100.000
        if parsed_numbers:
            min_val = parsed_numbers[0]
            
    return {"min_isee": min_val, "max_isee": max_val, "scholarship": False}

def fetch_rates():
    url = "https://www.dsu.toscana.it/-/tariffa-agevolata-su-base-isee"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the table containing "Fascia ISEE"
        table = None
        for t in soup.find_all('table'):
            if "Fascia ISEE" in t.get_text():
                table = t
                break
        
        if not table:
            print("Table not found on the page.")
            return

        rates_data = []
        
        # Iterate over rows (skipping the header)
        rows = table.find_all('tr')
        
        for row in rows[1:]:
            cols = row.find_all('td')
            if len(cols) < 5:
                continue
            
            raw_isee = clean_text(cols[0].get_text())
            # Skip empty rows if any
            if not raw_isee: continue

            isee_info = parse_isee_range(raw_isee)
            
            # Format price as float
            pasto_completo = parse_money(cols[1].get_text())
            pasto_ridotto_a = parse_money(cols[2].get_text())
            pasto_ridotto_b = parse_money(cols[3].get_text())
            pasto_ridotto_c = parse_money(cols[4].get_text())

            entry = {
                "min_isee": isee_info["min_isee"],
                "max_isee": isee_info["max_isee"] if isee_info["max_isee"] != float('inf') else "MAX",
                "scholarship": isee_info["scholarship"],
                "pasto_completo": pasto_completo,
                "pasto_ridotto_a": pasto_ridotto_a,
                "pasto_ridotto_b": pasto_ridotto_b,
                "pasto_ridotto_c": pasto_ridotto_c,
                "original_label": raw_isee # Keeping it just in case
            }
            # For JSON serialization of infinity, we need to handle it. json dump does not support infinity by default for standard JSON, but let's just use string "MAX" or null.
            # I used "MAX" string above for readability for the user, but maybe null is better for code.
            # User wants "da che valore ... a che valore".
            # Let's stick with specific keys.
            
            if entry["max_isee"] == "MAX":
                 entry["max_isee"] = None # JSON null
                 
            rates_data.append(entry)
            
        # Write to JSON
        with open('rates.json', 'w', encoding='utf-8') as f:
            json.dump(rates_data, f, indent=4, ensure_ascii=False)
            
        print(f"Successfully extracted {len(rates_data)} rates to rates.json")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_rates()

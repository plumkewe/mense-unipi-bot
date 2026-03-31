import json
import os
import argparse

FESTE_PATH = "data/feste.json"

def main():
    parser = argparse.ArgumentParser(description="Gestisci chiusure mense.")
    parser.add_argument("--canteen", required=True, help="ID della mensa")
    parser.add_argument("--start", required=True, help="Data inizio (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="Data fine (YYYY-MM-DD)")
    parser.add_argument("--status", required=True, choices=["closed", "lunch_only", "dinner_only"], help="Stato della mensa")
    args = parser.parse_args()

    if os.path.exists(FESTE_PATH):
        with open(FESTE_PATH, "r", encoding="utf-8") as f:
            feste = json.load(f)
    else:
        feste = {}

    canteen = args.canteen
    if canteen not in feste:
        feste[canteen] = []

    # Aggiungi o aggiorna il periodo
    # Cerchiamo di evitare duplicati esatti
    new_entry = {
        "start_date": args.start,
        "end_date": args.end,
        "status": args.status
    }
    
    # Rimuovi vecchie entry se si sovrappongono esattamente
    feste[canteen] = [e for e in feste[canteen] if not (e["start_date"] == args.start and e["end_date"] == args.end)]
    feste[canteen].append(new_entry)

    # Scrivi sul file
    with open(FESTE_PATH, "w", encoding="utf-8") as f:
        json.dump(feste, f, indent=2, ensure_ascii=False)
        f.write("\n")

if __name__ == "__main__":
    main()

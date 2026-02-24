
import json
import matplotlib.pyplot as plt
import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

def format_price(value):
    """Formats price float to string (e.g. 2.8 -> € 2,80) or 'Gratuito'"""
    if isinstance(value, (int, float)):
        if value <= 0:
            return "Gratuito"
        return f"€ {value:.2f}".replace('.', ',')
    return str(value)

def generate_table():
    json_path = os.path.join(DATA_DIR, 'rates.json')
    output_path = os.path.join(REPO_DIR, 'assets', 'img', 'table.png')

    if not os.path.exists(json_path):
        print(f"File {json_path} not found.")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Prepare data for DataFrame
    rows = []
    for item in data:
        row = {
            "Fascia ISEE": item.get('original_label', ''),
            "Pasto completo": format_price(item.get('pasto_completo', 0)),
            "Pasto ridotto A": format_price(item.get('pasto_ridotto_a', 0)),
            "Pasto ridotto B": format_price(item.get('pasto_ridotto_b', 0)),
            "Pasto ridotto C": format_price(item.get('pasto_ridotto_c', 0)),
        }
        rows.append(row)

    # Ensure correct column order
    cols_order = ["Fascia ISEE", "Pasto completo", "Pasto ridotto A", "Pasto ridotto B", "Pasto ridotto C"]
    df = pd.DataFrame(rows, columns=cols_order)

    # Define colors
    bg_color = '#ebff00'       # Yellow background
    header_color = '#fc2947'   # Red header
    text_color = '#000000'     # Black text
    row_alt_color = '#f5ff80'  # Lighter yellow for alternating rows (or white)
    row_color = '#ffffff'      # White for standard rows

    # Plotting
    # Height calculation: header + rows (no title space needed)
    fig_height = (len(df) + 1) * 0.6
    fig, ax = plt.subplots(figsize=(16, fig_height)) 
    
    # Set background color
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    ax.axis('tight')
    ax.axis('off')

    # Create table
    # Column headers to uppercase and wrap
    col_labels = []
    for c in cols_order:
        label = c.upper()
        # Wrap "PASTO RIDOTTO X" to "PASTO\nRIDOTTO X"
        if "RIDOTTO" in label:
            label = label.replace("RIDOTTO", "\nRIDOTTO")
        elif "COMPLETO" in label:
            label = label.replace("COMPLETO", "\nCOMPLETO")
        
        col_labels.append(label)
    
    table = ax.table(
        cellText=df.values, 
        cellLoc='center',
        colLabels=col_labels, 
        loc='center', 
        colWidths=[0.30, 0.175, 0.175, 0.175, 0.175]
    )
    
    # Styling
    table.auto_set_font_size(False)
    table.set_fontsize(13) # Slightly smaller font
    table.scale(1, 4)    # Taller rows for "modern" look (increased to accommodate wrapped headers)

    for k, cell in table.get_celld().items():
        cell.set_edgecolor(text_color) # Black borders
        cell.set_linewidth(1.5)        # Thicker borders
        
        # Header (row 0)
        if k[0] == 0:
            cell.set_text_props(weight='bold', color=text_color)
            cell.set_facecolor(header_color)
            # cell.set_height(0.15) # Make header a bit taller if needed, but scale handles it generally
        # Data rows
        else:
            cell.set_text_props(color=text_color)
            # Alternating row colors
            # Row index k[0] starts at 1 for data
            if k[0] % 2 == 0:
                cell.set_facecolor(row_alt_color) # Light yellow
            else:
                cell.set_facecolor(row_color)     # White
            
    # Add a title or extra spacing at top if needed, but table handles it nicely centered.
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Save with background color and ~10px padding (0.05 inches at 300DPI is 15px, 0.033 is 10px)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1, dpi=300, facecolor=fig.get_facecolor())
    print(f"Table image saved to {output_path}")

if __name__ == "__main__":
    generate_table()

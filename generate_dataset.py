"""Generates the bundled demo/sample dataset (clearly synthetic) for OneCode AI."""
import csv
import os

rows = []
counters = {}

def next_code(cpse):
    counters[cpse] = counters.get(cpse, 1000) + 1
    return f"{cpse}-{counters[cpse]}"

def add(cpse, desc, category, material, dim, unit, standard, grade="", pressure="", voltage="",
        manufacturer="", mfrpn="", price=0, qty=0, cluster=""):
    rows.append(dict(
        cpse_id=cpse, material_code=next_code(cpse), raw_description=desc, category=category,
        material=material, dimension_1=dim, unit=unit, standard=standard, grade=grade,
        pressure_rating=pressure, voltage_rating=voltage, manufacturer=manufacturer,
        manufacturer_part_number=mfrpn, unit_price=price, quantity_procured=qty,
        source="Demo CSV", true_cluster=cluster,
    ))

# BEARINGS
add("ONGC", "SKF BRG 6205 2RS", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", manufacturer="SKF", mfrpn="6205-2RS", price=420, qty=200, cluster="B1")
add("CPCL", "6205 2RS Deep Groove Bearing", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", price=445, qty=150, cluster="B1")
add("GAIL", "Bearing 6205-2RS", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", price=410, qty=300, cluster="B1")
add("IOCL", "DGBB 6205 2RS", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", price=400, qty=180, cluster="B1")
add("BPCL", "FAG Bearing 6205 2RS", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", manufacturer="FAG", price=460, qty=100, cluster="B2_equiv")
add("HPCL", "NSK BRG DGBB 6205-2RS", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", manufacturer="NSK", price=455, qty=120, cluster="B2_equiv")
add("NTPC", "SKF BRG 6205 open type", "Bearing", "Steel", "6205", "model", "ISO 15", "N/A", manufacturer="SKF", price=390, qty=80, cluster="B3_family")
add("SAIL", "Bearing 6205 - spec not confirmed", "Bearing", "", "6205", "model", "", "", price=400, qty=50, cluster="B_insufficient")

# FASTENERS
add("ONGC", "HEX BLT M12X50 SS304 DIN933 GR8.8", "Fastener", "SS304", "12x50", "mm", "DIN933", "8.8", price=12, qty=5000, cluster="F1")
add("CPCL", "Bolt Hexagonal M12 x 50mm Stainless 304 DIN 933 Grade 8.8", "Fastener", "SS304", "12x50", "mm", "DIN933", "8.8", price=14, qty=3000, cluster="F1")
add("GAIL", "BOLT HEX M12*50 SS304 DIN933 8.8", "Fastener", "SS304", "12x50", "mm", "DIN933", "8.8", price=13, qty=4200, cluster="F1")
add("BHEL", "HEX BOLT M12x50 SS304 DIN933 GR10.9", "Fastener", "SS304", "12x50", "mm", "DIN933", "10.9", price=16, qty=1000, cluster="F2_conflict")
add("IOCL", "Hex Bolt 0.5in x 2in SS304 DIN933 Grade 8.8", "Fastener", "SS304", "12.7x50.8", "inch", "DIN933", "8.8", price=15, qty=1800, cluster="F3_unit")

# PIPES
add("ONGC", "SS PIPE 50MM ASTM A312 TP304L", "Pipe", "Stainless Steel", "50", "mm", "ASTM A312", "TP304L", pressure="Sch40", price=850, qty=600, cluster="P1")
add("CPCL", "Stainless Steel Pipe 50mm ASTM A312 Grade TP304L Sch40", "Pipe", "Stainless Steel", "50", "mm", "ASTM A312", "TP304L", pressure="Sch40", price=880, qty=400, cluster="P1")
add("SAIL", "SS Pipe 50mm ASTM A312 TP304L Sch80", "Pipe", "Stainless Steel", "50", "mm", "ASTM A312", "TP304L", pressure="Sch80", price=1100, qty=250, cluster="P2_conflict")
add("NTPC", "SS Pipe 50mm A312 TP304L Sch40 threaded end", "Pipe", "Stainless Steel", "50", "mm", "ASTM A312", "TP304L", pressure="Sch40", price=900, qty=150, cluster="P3_family")
add("BPCL", "Pipe 50mm - material grade TBD", "Pipe", "", "50", "mm", "", "", pressure="", price=800, qty=100, cluster="P_insufficient")

# VALVES
add("ONGC", "GATE VALVE 100MM CLASS150 CS BODY", "Valve", "Carbon Steel", "100", "mm", "API600", "N/A", pressure="150#", price=4200, qty=40, cluster="V1")
add("CPCL", "Gate Valve 100mm Class 150 Carbon Steel Body API 600", "Valve", "Carbon Steel", "100", "mm", "API600", "N/A", pressure="150#", price=4350, qty=30, cluster="V1")
add("HPCL", "Gate Valve 100mm Class300 CS Body API600", "Valve", "Carbon Steel", "100", "mm", "API600", "N/A", pressure="300#", price=5800, qty=20, cluster="V2_conflict")

# CABLES
add("SAIL", "XLPE CABLE 3C 95SQMM 11KV", "Cable", "Copper", "95", "sqmm", "IS7098", "N/A", voltage="11kV", price=680, qty=2000, cluster="C1")
add("GAIL", "XLPE Cable 3 Core 95 sq mm 11 kV IS 7098", "Cable", "Copper", "95", "sqmm", "IS7098", "N/A", voltage="11kV", price=705, qty=1500, cluster="C1")
add("ONGC", "XLPE Cable 3C 95sqmm 33kV IS7098", "Cable", "Copper", "95", "sqmm", "IS7098", "N/A", voltage="33kV", price=980, qty=800, cluster="C2_conflict")

if __name__ == "__main__":
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample_materials.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Generated {len(rows)} rows across {len(set(r['category'] for r in rows))} categories, "
          f"{len(set(r['cpse_id'] for r in rows))} CPSEs -> {out_path}")

"""
main.py
-------
Flask backend for the Solar PV Yield Calculator.
"""

from flask import Flask, request, jsonify, send_file, Response
import os
import io
import json
import requests as http_requests
from datetime import datetime
from nasa_api import fetch_solar_irradiance
from calculator import run_full_calculation, calculate_monthly_energy, calculate_savings

app = Flask(__name__)

# Read index.html at startup (works on Vercel serverless)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_BASE_DIR, "templates", "index.html"), "r", encoding="utf-8") as _f:
    _INDEX_HTML = _f.read()

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import cm
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

INDIAN_CITY_PRESETS = {
    "Mumbai":    {"lat": 19.076, "lon": 72.877, "tilt": 19},
    "Delhi":     {"lat": 28.704, "lon": 77.102, "tilt": 29},
    "Bengaluru": {"lat": 12.972, "lon": 77.594, "tilt": 13},
    "Chennai":   {"lat": 13.083, "lon": 80.270, "tilt": 13},
    "Kolkata":   {"lat": 22.573, "lon": 88.364, "tilt": 23},
    "Hyderabad": {"lat": 17.385, "lon": 78.487, "tilt": 17},
    "Jaipur":    {"lat": 26.912, "lon": 75.787, "tilt": 27},
    "Ahmedabad": {"lat": 23.023, "lon": 72.572, "tilt": 23},
    "Pune":      {"lat": 18.520, "lon": 73.856, "tilt": 19},
    "Bhopal":    {"lat": 23.259, "lon": 77.413, "tilt": 23},
}

# ─── Tariff Presets (NEW) ──────────────────────────────────────────────────────
# Sources: State Electricity Regulatory Commission (SERC) orders, FY 2023-24
# All rates in ₹/kWh. Slabs define tiered billing (limit=None means unlimited).

TARIFF_PRESETS = {
    "residential": {
        "label": "Residential / Domestic",
        "description": "For homes, apartments, and small households",
        "icon": "🏠",
        "states": {
            "Maharashtra": {
                "discom": "MSEDCL",
                "flat_rate": 9.06,
                "slabs": [
                    {"limit": 100,  "rate": 3.46, "label": "0–100 units"},
                    {"limit": 300,  "rate": 7.71, "label": "101–300 units"},
                    {"limit": 500,  "rate": 9.94, "label": "301–500 units"},
                    {"limit": None, "rate": 11.22,"label": "500+ units"},
                ]
            },
            "Delhi": {
                "discom": "BSES / Tata Power",
                "flat_rate": 7.00,
                "slabs": [
                    {"limit": 200,  "rate": 3.00, "label": "0–200 units"},
                    {"limit": 400,  "rate": 4.50, "label": "201–400 units"},
                    {"limit": 800,  "rate": 6.50, "label": "401–800 units"},
                    {"limit": None, "rate": 8.00, "label": "800+ units"},
                ]
            },
            "Karnataka": {
                "discom": "BESCOM",
                "flat_rate": 7.10,
                "slabs": [
                    {"limit": 30,   "rate": 3.15, "label": "0–30 units"},
                    {"limit": 100,  "rate": 5.55, "label": "31–100 units"},
                    {"limit": 200,  "rate": 6.60, "label": "101–200 units"},
                    {"limit": None, "rate": 8.30, "label": "200+ units"},
                ]
            },
            "Tamil Nadu": {
                "discom": "TNEB",
                "flat_rate": 5.80,
                "slabs": [
                    {"limit": 100,  "rate": 0.00, "label": "0–100 units (Free)"},
                    {"limit": 200,  "rate": 1.50, "label": "101–200 units"},
                    {"limit": 500,  "rate": 3.00, "label": "201–500 units"},
                    {"limit": None, "rate": 6.00, "label": "500+ units"},
                ]
            },
            "Rajasthan": {
                "discom": "JVVNL / AVVNL",
                "flat_rate": 6.50,
                "slabs": [
                    {"limit": 50,   "rate": 3.50, "label": "0–50 units"},
                    {"limit": 150,  "rate": 5.00, "label": "51–150 units"},
                    {"limit": 300,  "rate": 6.50, "label": "151–300 units"},
                    {"limit": None, "rate": 8.00, "label": "300+ units"},
                ]
            },
            "Gujarat": {
                "discom": "UGVCL / DGVCL",
                "flat_rate": 5.50,
                "slabs": [
                    {"limit": 50,   "rate": 2.05, "label": "0–50 units"},
                    {"limit": 200,  "rate": 3.50, "label": "51–200 units"},
                    {"limit": None, "rate": 5.50, "label": "200+ units"},
                ]
            },
            "Telangana": {
                "discom": "TSSPDCL / TSNPDCL",
                "flat_rate": 6.00,
                "slabs": [
                    {"limit": 50,   "rate": 1.45, "label": "0–50 units"},
                    {"limit": 100,  "rate": 2.65, "label": "51–100 units"},
                    {"limit": 200,  "rate": 4.25, "label": "101–200 units"},
                    {"limit": None, "rate": 7.20, "label": "200+ units"},
                ]
            },
            "Uttar Pradesh": {
                "discom": "UPPCL",
                "flat_rate": 6.50,
                "slabs": [
                    {"limit": 100,  "rate": 3.35, "label": "0–100 units"},
                    {"limit": 150,  "rate": 4.35, "label": "101–150 units"},
                    {"limit": None, "rate": 6.00, "label": "150+ units"},
                ]
            },
            "West Bengal": {
                "discom": "WBSEDCL / CESC",
                "flat_rate": 7.50,
                "slabs": [
                    {"limit": 75,   "rate": 5.00, "label": "0–75 units"},
                    {"limit": 175,  "rate": 6.19, "label": "76–175 units"},
                    {"limit": None, "rate": 8.50, "label": "175+ units"},
                ]
            },
            "Punjab": {
                "discom": "PSPCL",
                "flat_rate": 7.68,
                "slabs": [
                    {"limit": 100,  "rate": 4.99, "label": "0–100 units"},
                    {"limit": 300,  "rate": 6.58, "label": "101–300 units"},
                    {"limit": None, "rate": 7.68, "label": "300+ units"},
                ]
            },
        }
    },
    "industrial": {
        "label": "Industrial / Commercial",
        "description": "For factories, offices, shops, and businesses",
        "icon": "🏭",
        "states": {
            "Maharashtra": {
                "discom": "MSEDCL",
                "flat_rate": 11.42,
                "slabs": [
                    {"limit": 500,  "rate": 9.36,  "label": "0–500 units (LT Commercial)"},
                    {"limit": None, "rate": 11.42, "label": "500+ units"},
                ],
                "note": "HT Industrial: ₹6.76/kWh + demand charges"
            },
            "Delhi": {
                "discom": "BSES / Tata Power",
                "flat_rate": 9.50,
                "slabs": [
                    {"limit": 500,  "rate": 7.50, "label": "0–500 units"},
                    {"limit": None, "rate": 9.50, "label": "500+ units"},
                ],
                "note": "Excludes fixed charges and TOD surcharge"
            },
            "Karnataka": {
                "discom": "BESCOM",
                "flat_rate": 8.45,
                "slabs": [
                    {"limit": 500,  "rate": 6.80, "label": "0–500 units"},
                    {"limit": None, "rate": 8.45, "label": "500+ units"},
                ]
            },
            "Tamil Nadu": {
                "discom": "TNEB",
                "flat_rate": 8.50,
                "slabs": [
                    {"limit": 500,  "rate": 6.50, "label": "0–500 units (LT III)"},
                    {"limit": None, "rate": 8.50, "label": "500+ units"},
                ]
            },
            "Rajasthan": {
                "discom": "JVVNL / AVVNL",
                "flat_rate": 9.00,
                "slabs": [
                    {"limit": None, "rate": 9.00, "label": "Flat commercial rate"},
                ]
            },
            "Gujarat": {
                "discom": "UGVCL / DGVCL",
                "flat_rate": 7.80,
                "slabs": [
                    {"limit": None, "rate": 7.80, "label": "LT Industrial flat"},
                ],
                "note": "HT consumers have separate demand-based billing"
            },
            "Telangana": {
                "discom": "TSSPDCL / TSNPDCL",
                "flat_rate": 9.50,
                "slabs": [
                    {"limit": None, "rate": 9.50, "label": "LT Commercial / Industrial"},
                ]
            },
            "Uttar Pradesh": {
                "discom": "UPPCL",
                "flat_rate": 8.50,
                "slabs": [
                    {"limit": None, "rate": 8.50, "label": "LT Industrial flat rate"},
                ]
            },
            "West Bengal": {
                "discom": "WBSEDCL / CESC",
                "flat_rate": 9.20,
                "slabs": [
                    {"limit": None, "rate": 9.20, "label": "Commercial flat rate"},
                ]
            },
            "Punjab": {
                "discom": "PSPCL",
                "flat_rate": 8.46,
                "slabs": [
                    {"limit": None, "rate": 8.46, "label": "Industrial flat rate"},
                ]
            },
        }
    }
}


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return Response(_INDEX_HTML, mimetype="text/html")


@app.route("/api/presets", methods=["GET"])
def get_presets():
    return jsonify(INDIAN_CITY_PRESETS)


@app.route("/api/tariffs", methods=["GET"])
def get_tariffs():
    """
    Returns residential and industrial tariff presets for Indian states.
    Optional query param: category=residential|industrial
    Optional query param: state=Maharashtra (filter by state)
    """
    category = request.args.get("category", None)
    state    = request.args.get("state", None)

    if category and category in TARIFF_PRESETS:
        result = {category: TARIFF_PRESETS[category]}
    else:
        result = TARIFF_PRESETS

    # Filter by state if requested
    if state:
        for cat in result:
            states = result[cat].get("states", {})
            if state in states:
                result[cat] = {**result[cat], "states": {state: states[state]}}

    return jsonify(result)


@app.route("/api/search-location", methods=["GET"])
def search_location():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify({"error": "Query too short. Please enter at least 2 characters."}), 400

    try:
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query,
            "format": "json",
            "limit": 5,
            "addressdetails": 1,
        }
        headers = {"User-Agent": "SolarPVCalculator/1.0 (contact@solarpv.app)"}

        resp = http_requests.get(nominatim_url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            return jsonify({"results": [], "message": "No locations found. Try a different name."})

        results = []
        for place in raw:
            lat = float(place["lat"])
            lon = float(place["lon"])
            suggested_tilt = round(abs(lat))
            address = place.get("address", {})
            parts = [
                address.get("city") or address.get("town") or address.get("village") or address.get("county"),
                address.get("state"),
                address.get("country"),
            ]
            display_name = ", ".join(p for p in parts if p) or place.get("display_name", "Unknown")
            results.append({
                "display_name": display_name,
                "full_name": place.get("display_name", ""),
                "lat": lat,
                "lon": lon,
                "suggested_tilt": suggested_tilt,
                "type": place.get("type", ""),
            })

        return jsonify({"results": results})

    except http_requests.Timeout:
        return jsonify({"error": "Location search timed out. Please try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Location search failed: {str(e)}"}), 500


@app.route("/api/calculate", methods=["POST"])
def calculate():
    """
    Main calculation endpoint.
    Now accepts optional tariff_slabs for slab-based billing.
    """
    try:
        data = request.get_json()

        required = ["latitude", "longitude", "capacity_kw", "efficiency",
                    "tilt_angle", "shading_loss", "electricity_rate"]
        for field in required:
            if field not in data:
                return jsonify({"error": f"Missing field: {field}"}), 400

        inputs = {
            "latitude":         float(data["latitude"]),
            "longitude":        float(data["longitude"]),
            "capacity_kw":      float(data["capacity_kw"]),
            "efficiency":       float(data["efficiency"]),
            "tilt_angle":       float(data["tilt_angle"]),
            "shading_loss":     float(data["shading_loss"]),
            "electricity_rate": float(data["electricity_rate"]),
            "monthly_bill":     float(data.get("monthly_bill", 2000)),
            # NEW: optional slab-based tariff
            "tariff_slabs":     data.get("tariff_slabs", None),
            "tariff_category":  data.get("tariff_category", "custom"),
            "tariff_state":     data.get("tariff_state", ""),
        }

        irradiance = fetch_solar_irradiance(inputs["latitude"], inputs["longitude"])
        results = run_full_calculation(inputs, irradiance)
        results["inputs"] = inputs

        return jsonify({"success": True, "data": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/compare", methods=["POST"])
def compare():
    """Compare two solar system sizes side-by-side."""
    try:
        data = request.get_json()
        lat  = float(data["latitude"])
        lon  = float(data["longitude"])
        eff  = float(data["efficiency"])
        tilt = float(data["tilt_angle"])
        shad = float(data["shading_loss"])
        rate = float(data["electricity_rate"])
        kw1  = float(data["capacity_kw_1"])
        kw2  = float(data["capacity_kw_2"])
        slabs = data.get("tariff_slabs", None)

        irradiance = fetch_solar_irradiance(lat, lon)

        def build_summary(capacity_kw):
            energy  = calculate_monthly_energy(irradiance, capacity_kw, eff, tilt, shad, lat)
            savings = calculate_savings(energy, rate, slabs)
            yearly_kwh = round(sum(energy), 2)
            yearly_inr = round(sum(savings), 2)
            return {
                "capacity_kw":      capacity_kw,
                "yearly_kwh":       yearly_kwh,
                "yearly_savings":   yearly_inr,
                "monthly_energy":   energy,
                "monthly_savings":  savings,
                "install_cost":     round(capacity_kw * 50000, 0),
                "payback_years":    round((capacity_kw * 50000) / yearly_inr, 1) if yearly_inr > 0 else None,
            }

        return jsonify({
            "success": True,
            "system1": build_summary(kw1),
            "system2": build_summary(kw2),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report", methods=["POST"])
def generate_report():
    """Generate and return a downloadable PDF report."""
    if not PDF_AVAILABLE:
        return jsonify({"error": "PDF library not installed. Run: pip install reportlab"}), 500

    try:
        data    = request.get_json()
        results = data.get("results", {})
        inputs  = data.get("inputs", {})

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=2*cm, leftMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        story  = []

        title_style = ParagraphStyle("Title", parent=styles["Title"],
                                     fontSize=20, textColor=colors.HexColor("#f97316"),
                                     spaceAfter=6)
        story.append(Paragraph("☀ Solar PV Yield Report", title_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}",
                               styles["Normal"]))
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("System Details", styles["Heading2"]))

        # Show tariff info in report
        tariff_label = ""
        if inputs.get("tariff_category") and inputs["tariff_category"] != "custom":
            tariff_label = f"{inputs.get('tariff_category','').title()} – {inputs.get('tariff_state','')}"
        else:
            tariff_label = "Custom"

        sys_data = [
            ["Parameter", "Value"],
            ["Location (Lat, Lon)", f"{inputs.get('latitude','')}, {inputs.get('longitude','')}"],
            ["System Capacity",     f"{inputs.get('capacity_kw','')} kW"],
            ["Panel Efficiency",    f"{inputs.get('efficiency','')}%"],
            ["Tilt Angle",          f"{inputs.get('tilt_angle','')}°"],
            ["Shading Loss",        f"{inputs.get('shading_loss','')}%"],
            ["Tariff Type",         tariff_label],
            ["Electricity Rate",    f"₹{inputs.get('electricity_rate','')}/kWh"],
        ]
        t = Table(sys_data, colWidths=[8*cm, 8*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,0), colors.HexColor("#f97316")),
            ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#fff7ed")]),
            ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#fed7aa")),
            ("FONTSIZE",     (0,0), (-1,-1), 10),
            ("PADDING",      (0,0), (-1,-1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph("Energy Output", styles["Heading2"]))
        yearly = results.get("yearly", {})
        daily  = results.get("daily", {})
        energy_data = [
            ["Metric", "Value"],
            ["Daily Energy",    f"{daily.get('energy_kwh',0)} kWh"],
            ["Yearly Energy",   f"{yearly.get('energy_kwh',0)} kWh"],
            ["Yearly Savings",  f"₹{yearly.get('savings_inr',0):,}"],
            ["CO₂ Reduction",   f"{yearly.get('co2_kg',0)} kg/year"],
            ["Trees Equivalent",f"{yearly.get('trees_equiv',0)} trees"],
        ]
        t2 = Table(energy_data, colWidths=[8*cm, 8*cm])
        t2.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#16a34a")),
            ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#f0fdf4")]),
            ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#bbf7d0")),
            ("FONTSIZE",      (0,0), (-1,-1), 10),
            ("PADDING",       (0,0), (-1,-1), 6),
        ]))
        story.append(t2)
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph("Return on Investment", styles["Heading2"]))
        roi = results.get("roi", {})
        roi_data = [
            ["Metric", "Value"],
            ["Installation Cost",      f"₹{int(roi.get('total_cost',0)):,}"],
            ["Payback Period",         f"{roi.get('payback_years','N/A')} years"],
            ["25-Year Total Savings",  f"₹{int(roi.get('total_25yr_savings',0)):,}"],
            ["25-Year ROI",            f"{roi.get('roi_25yr','N/A')}%"],
        ]
        t3 = Table(roi_data, colWidths=[8*cm, 8*cm])
        t3.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#7c3aed")),
            ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#faf5ff")]),
            ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#ddd6fe")),
            ("FONTSIZE",      (0,0), (-1,-1), 10),
            ("PADDING",       (0,0), (-1,-1), 6),
        ]))
        story.append(t3)
        story.append(Spacer(1, 0.5*cm))

        story.append(Paragraph("Monthly Breakdown", styles["Heading2"]))
        monthly = results.get("monthly", {})
        month_rows = [["Month", "Energy (kWh)", "Savings (₹)", "CO₂ Saved (kg)"]]
        for i, name in enumerate(monthly.get("names", [])):
            month_rows.append([
                name,
                str(monthly["energy"][i]),
                f"₹{monthly['savings'][i]:,}",
                str(monthly["co2"][i]),
            ])
        t4 = Table(month_rows, colWidths=[3*cm, 4*cm, 4.5*cm, 4.5*cm])
        t4.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0369a1")),
            ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
            ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#f0f9ff")]),
            ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#bae6fd")),
            ("FONTSIZE",      (0,0), (-1,-1), 9),
            ("PADDING",       (0,0), (-1,-1), 5),
        ]))
        story.append(t4)

        story.append(Spacer(1, 0.8*cm))
        story.append(Paragraph(
            "⚡ Generated by Solar PV Yield Calculator | Data source: NASA POWER API",
            ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
        ))

        doc.build(story)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name="solar_pv_report.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)

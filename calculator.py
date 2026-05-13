"""
calculator.py
-------------
Core solar PV yield calculation engine.
Handles energy output, savings, CO2, ROI, battery sizing, and more.
Now supports slab-based tariff calculation for residential and industrial users.
"""

import math
from sklearn.linear_model import LinearRegression
import numpy as np

# ─── Constants ────────────────────────────────────────────────────────────────
SYSTEM_LOSS_FACTOR   = 0.86   # Wiring (3%) + Inverter (4%) + Dust/misc (7%)
CO2_PER_KWH          = 0.82   # kg CO2 avoided per kWh (India grid factor)
DEGRADATION_RATE     = 0.005  # 0.5% panel degradation per year
DAYS_IN_MONTHS       = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
MONTH_NAMES          = ["Jan","Feb","Mar","Apr","May","Jun",
                         "Jul","Aug","Sep","Oct","Nov","Dec"]

# Monsoon/seasonal loss factors for India (1.0 = no extra loss)
INDIA_SEASONAL_LOSS  = [1.00, 1.00, 0.98, 0.97, 0.95, 0.80,
                         0.65, 0.65, 0.80, 0.95, 0.98, 1.00]


def tilt_correction_factor(tilt_angle: float, latitude: float) -> float:
    """
    Applies a simple cosine-based tilt angle correction.
    Optimal tilt ≈ latitude for most of India.
    """
    optimal_tilt = abs(latitude)
    delta = abs(tilt_angle - optimal_tilt)
    factor = 1.0 - min(delta * 0.005, 0.15)
    return round(factor, 4)


def optimal_tilt(latitude: float) -> float:
    """Recommended panel tilt angle based on latitude."""
    return round(abs(latitude) * 0.9 + 5, 1)


def effective_tariff_from_slabs(monthly_kwh: float, slabs: list) -> float:
    """
    Calculate the effective (average) tariff rate for a given monthly consumption
    using a tiered slab structure.

    slabs: list of dicts like:
        [
            {"limit": 100, "rate": 3.50},   # 0–100 kWh @ ₹3.50
            {"limit": 200, "rate": 5.00},   # 101–200 kWh @ ₹5.00
            {"limit": None, "rate": 7.00},  # 201+ kWh @ ₹7.00 (None = unlimited)
        ]

    Returns: effective average rate (₹/kWh)
    """
    if not slabs:
        return 0.0

    total_cost = 0.0
    remaining = monthly_kwh
    prev_limit = 0

    for slab in slabs:
        limit = slab.get("limit")
        rate = slab["rate"]

        if limit is None:
            # Last slab — all remaining units
            total_cost += remaining * rate
            remaining = 0
            break
        else:
            slab_units = limit - prev_limit
            units_in_slab = min(remaining, slab_units)
            total_cost += units_in_slab * rate
            remaining -= units_in_slab
            prev_limit = limit
            if remaining <= 0:
                break

    if monthly_kwh > 0:
        return round(total_cost / monthly_kwh, 4)
    return 0.0


def calculate_monthly_energy(
    irradiance: dict,
    capacity_kw: float,
    efficiency: float,
    tilt_angle: float,
    shading_loss: float,
    latitude: float,
    year_offset: int = 0
) -> list:
    """
    Calculates monthly energy output (kWh) for a given system.
    Returns a list of 12 monthly energy values.
    """
    tilt_factor = tilt_correction_factor(tilt_angle, latitude)
    shading_factor = 1.0 - (shading_loss / 100.0)
    degradation_factor = (1 - DEGRADATION_RATE) ** year_offset

    monthly_energy = []
    for month_idx in range(12):
        month_num = month_idx + 1
        daily_irr = irradiance.get(month_num, 4.5)
        days = DAYS_IN_MONTHS[month_idx]
        seasonal = INDIA_SEASONAL_LOSS[month_idx]

        daily_kwh = (
            daily_irr
            * capacity_kw
            * (efficiency / 100.0)
            * tilt_factor
            * shading_factor
            * SYSTEM_LOSS_FACTOR
            * seasonal
            * degradation_factor
        )
        monthly_kwh = round(daily_kwh * days, 2)
        monthly_energy.append(monthly_kwh)

    return monthly_energy


def calculate_savings(monthly_energy: list, rate: float, slabs: list = None) -> list:
    """
    Returns monthly savings in ₹.
    If slabs are provided, uses slab-based effective tariff per month.
    Otherwise uses flat rate.
    """
    savings = []
    for energy in monthly_energy:
        if slabs:
            effective_rate = effective_tariff_from_slabs(energy, slabs)
        else:
            effective_rate = rate
        savings.append(round(energy * effective_rate, 2))
    return savings


def calculate_co2(monthly_energy: list) -> list:
    """Returns monthly CO₂ reduction in kg."""
    return [round(e * CO2_PER_KWH, 2) for e in monthly_energy]


def battery_recommendation(monthly_energy: list, capacity_kw: float) -> dict:
    """
    Recommends battery size for 1-day and 2-day backup.
    Based on average daily usage.
    """
    yearly_kwh = sum(monthly_energy)
    avg_daily_kwh = yearly_kwh / 365
    one_day_kwh  = round(avg_daily_kwh / 0.80, 2)
    two_day_kwh  = round((avg_daily_kwh * 2) / 0.80, 2)

    return {
        "avg_daily_kwh": round(avg_daily_kwh, 2),
        "one_day_battery_kwh": one_day_kwh,
        "two_day_battery_kwh": two_day_kwh
    }


def zero_bill_system_size(
    monthly_bill: float,
    rate: float,
    irradiance: dict,
    efficiency: float,
    tilt_angle: float,
    shading_loss: float,
    latitude: float,
    slabs: list = None
) -> float:
    """
    Estimates system size (kW) needed to generate enough energy to zero out
    the user's monthly electricity bill.
    """
    monthly_consumption = monthly_bill / rate if rate > 0 else 0
    ref_energy = calculate_monthly_energy(irradiance, 1.0, efficiency, tilt_angle, shading_loss, latitude)
    avg_monthly_per_kw = sum(ref_energy) / 12
    if avg_monthly_per_kw == 0:
        return 0
    required_kw = monthly_consumption / avg_monthly_per_kw
    return round(required_kw, 2)


def linear_regression_forecast(monthly_energy: list, years: int = 10) -> dict:
    """
    Simple AI-based (linear regression) future energy prediction.
    Accounts for panel degradation over time.
    """
    yearly_energy = [sum(monthly_energy) * ((1 - DEGRADATION_RATE) ** y) for y in range(years)]
    X = np.array(range(years)).reshape(-1, 1)
    y = np.array(yearly_energy)

    model = LinearRegression()
    model.fit(X, y)

    future_years = list(range(years))
    predictions = [round(model.predict([[yr]])[0], 2) for yr in future_years]

    return {
        "years": future_years,
        "predicted_kwh": predictions,
        "slope": round(float(model.coef_[0]), 2),
        "base_yearly_kwh": round(yearly_energy[0], 2)
    }


def roi_analysis(
    capacity_kw: float,
    yearly_savings: float,
    install_cost_per_kw: float = 50000
) -> dict:
    """
    Calculates ROI and payback period.
    Default installation cost: ₹50,000/kW (typical Indian market).
    """
    total_cost = capacity_kw * install_cost_per_kw
    if yearly_savings <= 0:
        return {"total_cost": total_cost, "payback_years": None, "roi_25yr": None}

    payback_years = round(total_cost / yearly_savings, 1)
    total_25yr_savings = yearly_savings * 25
    roi_25yr = round(((total_25yr_savings - total_cost) / total_cost) * 100, 1)

    return {
        "total_cost": round(total_cost, 0),
        "payback_years": payback_years,
        "roi_25yr": roi_25yr,
        "total_25yr_savings": round(total_25yr_savings, 0)
    }


def run_full_calculation(inputs: dict, irradiance: dict) -> dict:
    """
    Master function: runs all calculations and returns a complete results dict.
    Supports flat rate or slab-based tariff.
    """
    lat          = inputs["latitude"]
    capacity_kw  = inputs["capacity_kw"]
    efficiency   = inputs["efficiency"]
    tilt         = inputs["tilt_angle"]
    shading      = inputs["shading_loss"]
    rate         = inputs["electricity_rate"]
    monthly_bill = inputs.get("monthly_bill", 2000)
    slabs        = inputs.get("tariff_slabs", None)  # NEW: optional slab list

    # Monthly energy, savings, CO2
    monthly_energy  = calculate_monthly_energy(irradiance, capacity_kw, efficiency, tilt, shading, lat)
    monthly_savings = calculate_savings(monthly_energy, rate, slabs)
    monthly_co2     = calculate_co2(monthly_energy)

    yearly_energy  = round(sum(monthly_energy), 2)
    yearly_savings = round(sum(monthly_savings), 2)
    yearly_co2     = round(sum(monthly_co2), 2)

    # Recommendations
    battery      = battery_recommendation(monthly_energy, capacity_kw)
    opt_tilt     = optimal_tilt(lat)
    zero_bill_kw = zero_bill_system_size(monthly_bill, rate, irradiance, efficiency, tilt, shading, lat, slabs)
    forecast     = linear_regression_forecast(monthly_energy)
    roi          = roi_analysis(capacity_kw, yearly_savings)

    daily_energy  = round(yearly_energy / 365, 3)
    daily_savings = round(yearly_savings / 365, 2)

    return {
        "monthly": {
            "names":   MONTH_NAMES,
            "energy":  monthly_energy,
            "savings": monthly_savings,
            "co2":     monthly_co2
        },
        "yearly": {
            "energy_kwh":    yearly_energy,
            "savings_inr":   yearly_savings,
            "co2_kg":        yearly_co2,
            "trees_equiv":   round(yearly_co2 / 21.7, 1)
        },
        "daily": {
            "energy_kwh":    daily_energy,
            "savings_inr":   daily_savings
        },
        "battery":           battery,
        "optimal_tilt":      opt_tilt,
        "zero_bill_kw":      zero_bill_kw,
        "forecast":          forecast,
        "roi":               roi,
        "irradiance":        {str(k): v for k, v in irradiance.items()}
    }

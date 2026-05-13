"""
nasa_api.py
-----------
Fetches solar irradiance data from NASA POWER API (FREE, no key required).
API Docs: https://power.larc.nasa.gov/api/
"""

import requests

NASA_BASE_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"

def fetch_solar_irradiance(lat: float, lon: float) -> dict:
    """
    Fetches monthly average solar irradiance (kWh/m²/day) from NASA POWER API.

    Parameters:
        lat (float): Latitude of the location
        lon (float): Longitude of the location

    Returns:
        dict: Monthly irradiance values (Jan-Dec) or raises an exception
    """
    params = {
        "parameters": "ALLSKY_SFC_SW_DWN",   # All-sky surface shortwave downward irradiance
        "community": "RE",                    # Renewable Energy community
        "longitude": lon,
        "latitude": lat,
        "start": "2015",
        "end": "2022",
        "format": "JSON",
        "time-standard": "UTC"
    }

    try:
        response = requests.get(NASA_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Navigate to the monthly data
        monthly_data = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]

        # Average across years for each month (keys like "201501", "201502", ...)
        month_sums = {i: 0.0 for i in range(1, 13)}
        month_counts = {i: 0 for i in range(1, 13)}

        for key, value in monthly_data.items():
            if value != -999:  # NASA uses -999 for missing data
                month = int(key[-2:])
                if 1 <= month <= 12:
                    month_sums[month] += value
                    month_counts[month] += 1

        # Calculate averages (kWh/m²/day for each month)
        monthly_irradiance = {}
        for month in range(1, 13):
            if month_counts[month] > 0:
                monthly_irradiance[month] = round(month_sums[month] / month_counts[month], 3)
            else:
                monthly_irradiance[month] = 4.5  # fallback default

        return monthly_irradiance

    except requests.exceptions.Timeout:
        raise Exception("NASA API timed out. Please try again.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch NASA data: {str(e)}")
    except (KeyError, ValueError) as e:
        raise Exception(f"Unexpected NASA API response format: {str(e)}")

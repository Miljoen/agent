"""
Dutch Greenhouse Gas Emissions Dashboard
---------------------------------------

This Streamlit application connects to the CBS (Statistics Netherlands) open data
API to retrieve greenhouse‑gas emissions by climate sector for the Netherlands.
It then aggregates the data to highlight which sectors emit above the national
average and plots these values on a map.  The coordinates for each sector are
approximate representations of where the bulk of that sector’s emissions occur
(for example, industry is centred on the Port of Rotterdam).  When run, the
application will fetch the most recent data (you can change the period via
the drop‑down) and display action items for environmental enforcers.

**How it works**

1.  The function `get_emission_data` queries the CBS OData API for a given
    period and returns emissions per sector for three categories: total
    greenhouse gases, carbon dioxide (CO₂) and “other greenhouse gases”
    (methane, nitrous oxide and fluorinated gases).  The table ID `84979NED`
    corresponds to the CBS climate sector inventory【597134015243035†L0-L52】.

2.  A simple mean across sectors is calculated for each category to establish
    baseline (average) emissions.

3.  A folium map is generated centred on the Netherlands.  Each sector is
    represented by a circle whose colour indicates whether its total emissions
    exceed the average (red) or not (green).

4.  The `interpret_data` function produces a plain‑text list of action items
    highlighting sectors whose emissions are above average and recommending
    enforcement focus.

To run this app you’ll need to install the dependencies listed in
`requirements.txt` and then execute `streamlit run app.py` from a terminal.
"""

import json
import statistics
from typing import Dict, Tuple

import requests
import streamlit as st
import folium


def get_emission_data(period: str = "2023JJ00") -> Dict[str, Dict[str, float]]:
    """Fetch emission data from CBS OData API for a given period.

    The CBS table `84979NED` provides quarterly and annual greenhouse‑gas
    emissions by climate sector.  Each record in the table is keyed by a
    climate sector code (`Klimaatsector`), an emission type (`Emissies`) and
    a period (`Perioden`).  The metric `EmissieBroeikasgassen_1` holds the
    emissions expressed in billion kilograms CO₂‑equivalent【871866509512252†L1-L19】.

    Args:
        period: A string representing the period code (e.g. "2023JJ00" for
            the year 2023, "2024KW01" for 2024 Q1).  Valid period codes can
            be retrieved from the `Perioden` endpoint of the CBS API【130989130530488†L40-L63】.

    Returns:
        A dictionary keyed by human‑readable sector name containing a nested
        dictionary of emission categories ("total", "CO2" and "other") and
        their values in Mt CO₂‑equivalent.
    """
    base_url = "https://opendata.cbs.nl/ODataApi/odata/84979NED"
    # OData keys for emission categories
    categories = {
        "total": "T001372",   # total greenhouse gases
        "CO2": "A044109",     # carbon dioxide
        "other": "A050122",   # other greenhouse gases (CH₄, N₂O and F‑gases)
    }
    # Mapping of climate sector codes to descriptive names
    sectors = {
        "A050123": "Industrie",             # Industry【597134015243035†L10-L16】
        "A050124": "Elektriciteit",         # Electricity generation【597134015243035†L18-L22】
        "A050125": "Mobiliteit",            # Mobility (transport)【597134015243035†L24-L27】
        "A050126": "Landbouw",               # Agriculture【597134015243035†L29-L31】
        "A050127": "Gebouwde omgeving",      # Built environment【597134015243035†L33-L38】
        "A052138": "Landgebruik",            # Land use (LULUCF)【597134015243035†L40-L49】
    }
    results: Dict[str, Dict[str, float]] = {}
    for category_name, category_key in categories.items():
        # Build OData query: filter on period and emission category, select only the
        # relevant fields and request JSON output.  See example query results【188970336999570†L0-L25】.
        query = (
            f"{base_url}/TypedDataSet?"
            f"$filter=(Perioden%20eq%20'{period}')%20and%20(Emissies%20eq%20'{category_key}')"
            "&$select=Klimaatsector,EmissieBroeikasgassen_1&$format=json"
        )
        try:
            response = requests.get(query)
            response.raise_for_status()
            data = response.json().get("value", [])
        except Exception:
            # If the API cannot be reached (e.g. due to network restrictions),
            # fallback to an empty list.  The app will still load with no data.
            data = []
        for item in data:
            sector_key = item.get("Klimaatsector")
            # Skip the total row
            if sector_key == "T001616":
                continue
            sector_name = sectors.get(sector_key, sector_key)
            results.setdefault(sector_name, {})[category_name] = item.get(
                "EmissieBroeikasgassen_1", 0.0
            )
    return results


def compute_average(data: Dict[str, Dict[str, float]], category: str) -> float:
    """Compute the mean emissions across sectors for a given category."""
    values = [vals.get(category, 0.0) for vals in data.values()]
    return statistics.mean(values) if values else 0.0


def create_map(
    data: Dict[str, Dict[str, float]],
    averages: Dict[str, float],
    sector_coords: Dict[str, Tuple[float, float]],
) -> folium.Map:
    """Create a folium map with markers for each climate sector.

    Sectors with total emissions above the average are coloured red; those below
    the average are green.  Each marker displays a popup with emissions broken
    down by category.
    """
    # Centre of the Netherlands
    m = folium.Map(location=[52.2, 5.3], zoom_start=7, tiles="CartoDB positron")
    for sector, values in data.items():
        coord = sector_coords.get(sector)
        if not coord:
            continue
        total_emission = values.get("total", 0.0)
        marker_color = "green" if total_emission <= averages.get("total", 0.0) else "red"
        # Build HTML popup with category breakdown
        popup_html = (
            f"<b>{sector}</b><br>"
            f"Totale uitstoot: {total_emission:.1f} Mt CO₂-eq<br>"
            f"CO₂: {values.get('CO2', 0.0):.1f} Mt<br>"
            f"Overige gassen: {values.get('other', 0.0):.1f} Mt"
        )
        folium.CircleMarker(
            location=coord,
            radius=10,
            color=marker_color,
            fill=True,
            fill_color=marker_color,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(m)
    return m


def interpret_data(
    data: Dict[str, Dict[str, float]], averages: Dict[str, float]
) -> Dict[str, str]:
    """Generate action items for sectors emitting above the average.

    Returns:
        A dictionary keyed by sector with recommended enforcement actions as
        values.
    """
    actions: Dict[str, str] = {}
    for sector, vals in data.items():
        total = vals.get("total", 0.0)
        if total > averages.get("total", 0.0):
            actions[sector] = (
                f"De sector {sector} stoot {total:.1f} Mt CO₂-equivalent uit, wat boven "
                f"het gemiddelde van {averages['total']:.1f} Mt ligt. Controleer grote \
                installaties en voer aanvullende reductiemaatregelen uit."
            )
    return actions


def main() -> None:
    """Streamlit entry point."""
    st.set_page_config(page_title="NL Emissie Dashboard", layout="wide")
    st.title("Nederlandse broeikasgasuitstoot per klimaatsector")

    st.markdown(
        """
        Deze app haalt gegevens uit de **CBS open data API** en toont de
        uitstoot van broeikasgassen (in Mt CO₂-equivalent) per klimaatsector.
        Kies een periode om de kaart en analyse te actualiseren. Sectoren met
        een uitstoot boven het gemiddelde worden rood weergegeven.
        """
    )

    # Select period.  We list a few of the most recent periods manually; in
    # production you could query the `Perioden` endpoint to populate this.
    period = st.selectbox(
        "Kies periode", [
            "2025KW01", "2024KW04", "2024JJ00", "2023JJ00", "2022JJ00"
        ], index=2
    )
    data = get_emission_data(period)
    averages = {
        cat: compute_average(data, cat) for cat in ["total", "CO2", "other"]
    }
    # Approximate coordinates for each sector to map emissions to locations
    sector_coords = {
        "Industrie": (51.91086, 4.47858),          # Port of Rotterdam (industry)
        "Elektriciteit": (53.415, 6.83),         # Eemshaven (electricity)
        "Mobiliteit": (52.370216, 4.895168),     # Amsterdam (mobility hub)
        "Landbouw": (52.75, 5.3),                # Rural centre (agriculture)
        "Gebouwde omgeving": (52.09074, 5.12142), # Utrecht (built environment)
        "Landgebruik": (52.9896, 6.5649),        # Drenthe/forest area (land use)
    }
    # Create and display the map
    if data:
        map_obj = create_map(data, averages, sector_coords)
        st.components.v1.html(map_obj._repr_html_(), height=600, scrolling=False)
    else:
        st.warning(
            "Kon geen data ophalen van de CBS API. Controleer uw internetverbinding of API‑toegang."
        )

    st.subheader("Gemiddelde uitstoot per sector")
    st.write(
        {
            "Totale gassen": f"{averages['total']:.1f} Mt",
            "CO₂": f"{averages['CO2']:.1f} Mt",
            "Overige gassen": f"{averages['other']:.1f} Mt",
        }
    )
    st.subheader("Actiepunten voor toezichthouders")
    actions = interpret_data(data, averages)
    if actions:
        for sector, action in actions.items():
            st.write(f"- {action}")
    else:
        st.write("Geen sectoren boven het gemiddelde voor deze periode.")


if __name__ == "__main__":
    main()

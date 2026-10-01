"""Values the GST portal's GSTR-1 Excel template expects (ADR-050 item 9), copied from its
"master" sheet: ``GSTR1_Excel_Workbook_Template_V2.2.xlsx`` in the Returns Offline Tool V3.2.4
(gst.gov.in/download/returns; zip SHA-256 F0A7D6F6…E312), downloaded 2026-09-30. Checklist
item 26: compare with the latest template before relying on it."""

# Place of supply: "<state code>-<name>" exactly as the template lists them.
PLACE_OF_SUPPLY: dict[str, str] = {
    "01": "01-Jammu & Kashmir",
    "02": "02-Himachal Pradesh",
    "03": "03-Punjab",
    "04": "04-Chandigarh",
    "05": "05-Uttarakhand",
    "06": "06-Haryana",
    "07": "07-Delhi",
    "08": "08-Rajasthan",
    "09": "09-Uttar Pradesh",
    "10": "10-Bihar",
    "11": "11-Sikkim",
    "12": "12-Arunachal Pradesh",
    "13": "13-Nagaland",
    "14": "14-Manipur",
    "15": "15-Mizoram",
    "16": "16-Tripura",
    "17": "17-Meghalaya",
    "18": "18-Assam",
    "19": "19-West Bengal",
    "20": "20-Jharkhand",
    "21": "21-Odisha",
    "22": "22-Chhattisgarh",
    "23": "23-Madhya Pradesh",
    "24": "24-Gujarat",
    "25": "25-Daman & Diu",
    "26": "26-Dadra & Nagar Haveli & Daman & Diu",
    "27": "27-Maharashtra",
    "29": "29-Karnataka",
    "30": "30-Goa",
    "31": "31-Lakshdweep",
    "32": "32-Kerala",
    "33": "33-Tamil Nadu",
    "34": "34-Puducherry",
    "35": "35-Andaman & Nicobar Islands",
    "36": "36-Telangana",
    "37": "37-Andhra Pradesh",
    "38": "38-Ladakh",
    "97": "97-Other Territory",
}

# Unit Quantity Codes: "<code>-<name>" as the HSN summary expects.
UQC: dict[str, str] = {
    "BAG": "BAG-BAGS",
    "BAL": "BAL-BALE",
    "BDL": "BDL-BUNDLES",
    "BKL": "BKL-BUCKLES",
    "BOU": "BOU-BILLION OF UNITS",
    "BOX": "BOX-BOX",
    "BTL": "BTL-BOTTLES",
    "BUN": "BUN-BUNCHES",
    "CAN": "CAN-CANS",
    "CBM": "CBM-CUBIC METERS",
    "CCM": "CCM-CUBIC CENTIMETERS",
    "CMS": "CMS-CENTIMETERS",
    "CTN": "CTN-CARTONS",
    "DOZ": "DOZ-DOZENS",
    "DRM": "DRM-DRUMS",
    "GGK": "GGK-GREAT GROSS",
    "GMS": "GMS-GRAMMES",
    "GRS": "GRS-GROSS",
    "GYD": "GYD-GROSS YARDS",
    "KGS": "KGS-KILOGRAMS",
    "KLR": "KLR-KILOLITRE",
    "KME": "KME-KILOMETRE",
    "LTR": "LTR-LITRES",
    "MLT": "MLT-MILILITRE",
    "MTR": "MTR-METERS",
    "MTS": "MTS-METRIC TON",
    "NOS": "NOS-NUMBERS",
    "PAC": "PAC-PACKS",
    "PCS": "PCS-PIECES",
    "PRS": "PRS-PAIRS",
    "QTL": "QTL-QUINTAL",
    "ROL": "ROL-ROLLS",
    "SET": "SET-SETS",
    "SQF": "SQF-SQUARE FEET",
    "SQM": "SQM-SQUARE METERS",
    "SQY": "SQY-SQUARE YARDS",
    "TBS": "TBS-TABLETS",
    "TGM": "TGM-TEN GROSS",
    "THD": "THD-THOUSANDS",
    "TON": "TON-TONNES",
    "TUB": "TUB-TUBES",
    "UGS": "UGS-US GALLONS",
    "UNT": "UNT-UNITS",
    "YDS": "YDS-YARDS",
    "OTH": "OTH-OTHERS",
}
OTHER_UQC = UQC["OTH"]

# Fixed values used in the sheets (see the template's "Help Instruction").
DATE_FORMAT = "%d-%b-%Y"  # DD-MMM-YYYY, e.g. 24-May-2017
REGULAR_B2B = "Regular B2B"  # Invoice Type / Note Supply Type
OTHER_THAN_ECOMMERCE = "OE"  # B2CS Type
CREDIT_NOTE = "C"  # Note Type
UR_B2CL = "B2CL"  # CDNUR UR Type
INVOICES_NATURE = "Invoices for outward supply"  # docs: Nature of Document
CREDIT_NOTES_NATURE = "Credit Note"

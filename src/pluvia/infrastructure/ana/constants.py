"""Constants for the ANA SOAP web service."""

ANA_WSDL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx?WSDL"

SOAP_NAMESPACES = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "mrcs": "http://MRCS/",
}

DIFFGRAM_PATH = ".//{urn:schemas-microsoft-com:xml-diffgram-v1}diffgram"

STATION_TYPE_MAP = {
    "fluviometrica": "1",
    "pluviometrica": "2",
    "telemetric": None,
}

VARIABLE_MAP = {
    "chuva": ("Chuva", "2", "(mm)"),
    "nivel": ("Nivel", "1", "(m)"),
    "vazao": ("Vazao", "3", "(m3/s)"),
    "cota": ("Cota", "1", "(m)"),
}

TELEMETRIC_VARS = {"Chuva", "Nivel", "Vazao"}

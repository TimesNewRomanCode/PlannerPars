import requests

def send_group(data: list):
    url = "http://localhost:8000/api/parser"

    response = requests.post(
        url,
        json={"items": data},
        timeout=10,
    )

    response.raise_for_status()

    return response.json()
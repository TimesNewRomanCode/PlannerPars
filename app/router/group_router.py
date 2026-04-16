import requests

def send_group(groups_ary: list, address_name: str):
    url = "http://localhost:8000/api/get_groups/"

    response = requests.post(
        url,
        json={"GroupsList": groups_ary, "AddressName": address_name},
        timeout=10,
    )

    response.raise_for_status()

    return response.json()
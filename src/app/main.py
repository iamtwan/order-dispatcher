from fastapi import FastAPI, HTTPException, Request
from requests.adapters import HTTPAdapter, Retry
from pydantic import BaseModel
from typing import List, Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv
import uvicorn
import base64
import requests
import os

load_dotenv()

app = FastAPI()

CIN7_API_BASE_URL = os.getenv("CIN7_API_BASE_URL")
CIN7_USERNAME = os.getenv("CIN7_USERNAME")
CIN7_PASSWORD = os.getenv("CIN7_PASSWORD")
FAST_API_KEY = os.getenv("FAST_API_KEY")


class ShopifyOrder(BaseModel):
    name: str
    updatedAt: str
    createdAt: str


class ShopifyPayload(BaseModel):
    orders: List[ShopifyOrder]


def encode_basic_auth(username, password):
    credentials = f"{username}:{password}"
    token = base64.b64encode(credentials.encode())
    return f"Basic {token.decode('utf-8')}"


def determine_date_range(orders: List[ShopifyOrder]) -> Tuple[str, str]:
    dates = [datetime.fromisoformat(
        order.createdAt.replace("Z", "+00:00")) for order in orders]
    start_date = min(dates) - timedelta(days=3)
    end_date = max(dates)
    return start_date.strftime('%Y-%m-%dT%H:%M:%SZ'), end_date.strftime('%Y-%m-%dT%H:%M:%SZ')


def get_session_with_retries():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def fetch_cin7_orders(start_date: str, end_date: str) -> List[dict]:
    fields = "id,createdDate,reference,dispatchedDate"
    where = f"where=CreatedDate>='{start_date}' AND CreatedDate<='{end_date}'"
    page = 1
    rows = 250

    headers = {"Authorization": encode_basic_auth(
        CIN7_USERNAME, CIN7_PASSWORD)}
    url = f"{CIN7_API_BASE_URL}?fields={fields}&{where}&order=createdDate ASC&page={page}&rows={rows}"

    session = get_session_with_retries()
    try:
        response = session.get(url, headers=headers,
                               timeout=10)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as error:
        return None, str(error)


def prepare_cin7_updates(shopify_orders: List[ShopifyOrder], cin7_orders: List[dict]) -> List[dict]:
    updates = []
    for shopify_order in shopify_orders:
        for cin7_order in cin7_orders:
            if cin7_order["reference"] == shopify_order.name and not cin7_order.get("dispatchedDate"):
                updates.append({
                    "id": cin7_order["id"],
                    "dispatchedDate": shopify_order.createdAt
                })
    return updates


def update_cin7_orders(updates: List[dict]) -> dict:
    if not updates:
        return "No updates to process"

    headers = {"Authorization": encode_basic_auth(
        CIN7_USERNAME, CIN7_PASSWORD)}
    url = f"{CIN7_API_BASE_URL}"

    session = get_session_with_retries()
    try:
        response = session.put(url, headers=headers,
                               json=updates, timeout=10)
        response.raise_for_status()
        return "Orders updated successfully"
    except requests.exceptions.RequestException as error:
        return {"message": "Failed to update orders", "error": str(error)}


@app.post("/shopify-orders/")
async def update_orders(payload: ShopifyPayload, request: Request):
    api_key = request.headers.get('X-Api-Key')
    if api_key != FAST_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    start_date, end_date = determine_date_range(payload.orders)
    cin7_orders, error = fetch_cin7_orders(start_date, end_date)

    if cin7_orders is None:
        return {"message": "Failed to fetch orders from Cin7 due to an error.", "error": error}, 500
    elif not cin7_orders:
        return {"message": "No orders found in the specified date range."}, 200

    updates = prepare_cin7_updates(payload.orders, cin7_orders)
    update_cin7_orders(updates)

    return {"message": f"Successful process. {len(updates)} orders updated."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

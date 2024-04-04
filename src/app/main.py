from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Tuple
from datetime import datetime, timedelta
import uvicorn
import base64
import requests
import os
from dotenv import load_dotenv

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
    start_date = min(dates) - timedelta(days=1)
    end_date = max(dates)
    return start_date.strftime('%Y-%m-%dT%H:%M:%SZ'), end_date.strftime('%Y-%m-%dT%H:%M:%SZ')


def fetch_cin7_orders(start_date: str, end_date: str) -> List[dict]:
    fields = "id,createdDate,reference,dispatchedDate"
    where = f"where=CreatedDate>='{start_date}' AND CreatedDate<='{end_date}'"
    page = 1
    rows = 250

    headers = {"Authorization": encode_basic_auth(
        CIN7_USERNAME, CIN7_PASSWORD)}
    url = f"{CIN7_API_BASE_URL}?fields={fields}&{where}&order=createdDate ASC&page={page}&rows={rows}"

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        return []


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

    response = requests.put(url, headers=headers, json=updates)
    if response.status_code == 200:
        return "Orders updated successfully"
    else:
        return {"message": "Failed to update orders", "error": response.text}


@app.post("/shopify-orders/")
async def update_orders(payload: ShopifyPayload, request: Request):
    api_key = request.headers.get('X-Api-Key')
    if api_key != FAST_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    start_date, end_date = determine_date_range(payload.orders)

    cin7_orders = fetch_cin7_orders(start_date, end_date)

    updates = prepare_cin7_updates(payload.orders, cin7_orders)

    update_cin7_orders(updates)

    return {"message": "Orders updated successfully", "cin7 updates": len(updates)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
